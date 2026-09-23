"""過去日リプレイの価格ストア（🆕 P37）.

J-Quants の「日付指定・全銘柄一括」日足（`/equities/bars/daily?date=`）を日付ごとにローカルへ
キャッシュし、リプレイ日 D の時点で **D 以前の行しか返さない** 窓口（`AsOfView`）経由でのみ
読ませる。未来リークを「気をつけて書く」ではなく構造で防ぐのが目的で、D より後の日付を
要求すると `FutureDataAccessError` を送出する。

日付ごとの一括取得を母集団にするのは、その日に上場していた銘柄（後に上場廃止した銘柄も含む）
が自然に揃い、現在の銘柄マスタから遡ることによる生存者バイアスを避けられるため。
キャッシュは gzip CSV（pyarrow 非依存・pickle 不使用）。非営業日は空ファイルで記録して再取得しない。
"""

from __future__ import annotations

import bisect
import datetime
import logging
from collections.abc import Awaitable, Callable, Sequence
from pathlib import Path
from typing import Final

import pandas as pd

from backend.services.data.data_fetcher import _to_4digit_code
from backend.services.data.jquants_errors import JQuantsClientError
from backend.services.data.ranking_service import parse_subscription_range

logger = logging.getLogger(__name__)

DEFAULT_CACHE_DIR: Final[Path] = Path(__file__).resolve().parents[3] / "data" / "replay" / "bars"

# J-Quants 生フィールド → キャッシュ列。調整後の値を使う（分割・併合で価格系列が途切れないよう）。
_RAW_COLUMNS: Final[tuple[str, ...]] = ("Date", "Code", "AdjO", "AdjH", "AdjL", "AdjC", "AdjVo")
_OHLCV_RENAME: Final[dict[str, str]] = {
    "AdjO": "Open",
    "AdjH": "High",
    "AdjL": "Low",
    "AdjC": "Close",
    "AdjVo": "Volume",
}
_OHLCV_COLUMNS: Final[list[str]] = ["Open", "High", "Low", "Close", "Volume"]

# 日足取得の進捗ログ・ハートビート更新の間隔（日数）。
_PROGRESS_EVERY: Final[int] = 50

BarFetcher = Callable[[str], Awaitable[list[dict[str, object]]]]


class FutureDataAccessError(RuntimeError):
    """リプレイ日より後のデータへアクセスしようとした（未来リーク）."""


def _weekdays(start: str, end: str) -> list[str]:
    day = datetime.date.fromisoformat(start)
    last = datetime.date.fromisoformat(end)
    out: list[str] = []
    while day <= last:
        if day.weekday() < 5:
            out.append(day.isoformat())
        day += datetime.timedelta(days=1)
    return out


def _cache_path(cache_dir: Path, date: str) -> Path:
    return cache_dir / f"{date}.csv.gz"


async def ensure_bar_cache(
    start: str,
    end: str,
    *,
    cache_dir: Path = DEFAULT_CACHE_DIR,
    fetch: BarFetcher | None = None,
    on_progress: Callable[[str], Awaitable[None]] | None = None,
) -> int:
    """[start, end] の平日のうち未キャッシュの日だけ全銘柄日足を取得して保存し、取得した日数を返す.

    祝日は J-Quants が空リストを返すので、空ファイルとして記録して次回以降は問い合わせない。
    取得失敗（`JQuantsError`）は握り潰さず伝播させる（欠けた日を黙って飛ばすと、その日を
    非営業日と誤認してリプレイの時系列がずれるため）。
    """
    if fetch is None:
        from backend.services.data.jquants_client import jquants

        fetch = jquants.fetch_all_daily_bars
    cache_dir.mkdir(parents=True, exist_ok=True)
    fetched = 0
    lower_bound: str | None = None
    for date in _weekdays(start, end):
        path = _cache_path(cache_dir, date)
        if path.exists() or (lower_bound is not None and date < lower_bound):
            continue
        try:
            bars = await fetch(date)
        except JQuantsClientError as exc:
            # 契約プランの配信範囲より古い日は 400 + 範囲本文が返る。取得できない日として飛ばし、
            # 空ファイル（= 祝日）としては記録しない（プラン変更後に取り直せるように）。
            bounds = parse_subscription_range(exc)
            if bounds is None or date >= bounds[0]:
                raise
            lower_bound = bounds[0]
            logger.info("リプレイ用日足: %s より前は契約範囲外のため取得しません", lower_bound)
            continue
        frame = pd.DataFrame([{col: bar.get(col) for col in _RAW_COLUMNS} for bar in bars], columns=list(_RAW_COLUMNS))
        tmp = path.with_suffix(".tmp")
        frame.to_csv(tmp, index=False, compression="gzip")
        tmp.replace(path)  # 途中で落ちても壊れたキャッシュを残さない
        fetched += 1
        if fetched % _PROGRESS_EVERY == 0:
            logger.info("リプレイ用日足キャッシュ: %d 日分を取得（直近 %s）", fetched, date)
            if on_progress is not None:
                await on_progress(date)
    return fetched


def load_price_store(cache_dir: Path, start: str, end: str) -> PriceStore:
    """キャッシュ済みの [start, end] の日足から `PriceStore` を組み立てる."""
    frames = []
    for date in _weekdays(start, end):
        path = _cache_path(cache_dir, date)
        if not path.exists():
            continue
        frame = pd.read_csv(path, dtype={"Code": str, "Date": str}, compression="gzip")
        if not frame.empty:
            frames.append(frame)
    raw = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(columns=list(_RAW_COLUMNS))
    return PriceStore(raw)


class PriceStore:
    """全期間の日足を保持し、リプレイ日ごとの読み取り窓口（`view`）を払い出す.

    保持するフレーム自体は外へ渡さない。読み取りは必ず `view(as_of)` 経由。
    """

    def __init__(self, raw: pd.DataFrame) -> None:
        df = raw.dropna(subset=["AdjC"]).copy()
        df["Date"] = df["Date"].astype(str).str.slice(0, 10)
        df["Code"] = df["Code"].astype(str)
        self._trading_dates: list[str] = sorted(df["Date"].unique().tolist())
        # 全期間を dict のリストで持つと数百万個の dict で GB 単位になるため、日付ごとの小さな
        # DataFrame で持ち、`bars_on` が呼ばれた日だけ dict へ変換する。
        self._bars_by_date: dict[str, pd.DataFrame] = {
            str(date): group.drop(columns=["Date"]).set_index("Code", drop=False) for date, group in df.groupby("Date")
        }
        ohlcv = df.rename(columns=_OHLCV_RENAME)
        ohlcv["Date"] = pd.to_datetime(ohlcv["Date"])
        self._history: dict[str, pd.DataFrame] = {
            _to_4digit_code(code): group.set_index("Date").sort_index()[_OHLCV_COLUMNS].astype(float)
            for code, group in ohlcv.groupby("Code")
        }

    @property
    def trading_dates(self) -> list[str]:
        return list(self._trading_dates)

    def previous_trading_date(self, date: str) -> str | None:
        idx = bisect.bisect_left(self._trading_dates, date)
        return self._trading_dates[idx - 1] if idx > 0 else None

    def trading_dates_between(self, start: str, end: str) -> list[str]:
        lo = bisect.bisect_left(self._trading_dates, start)
        hi = bisect.bisect_right(self._trading_dates, end)
        return self._trading_dates[lo:hi]

    def view(self, as_of: str) -> AsOfView:
        if as_of not in self._bars_by_date:
            raise ValueError(f"リプレイ日 {as_of} はキャッシュ上の取引日ではありません")
        return AsOfView(self, as_of)

    def codes(self) -> Sequence[str]:
        return list(self._history)

    # AsOfView からのみ使う内部アクセサ（as_of の検査は AsOfView 側で行う）
    def _bars(self, date: str) -> pd.DataFrame | None:
        return self._bars_by_date.get(date)

    def _frame(self, code: str) -> pd.DataFrame | None:
        return self._history.get(code)


class AsOfView:
    """リプレイ日 `as_of` の大引け時点で確定していたデータだけを返す読み取り窓口."""

    def __init__(self, store: PriceStore, as_of: str) -> None:
        self._store = store
        self.as_of = as_of
        self._as_of_ts = pd.Timestamp(as_of)

    def assert_visible(self, date: str) -> None:
        """`date` が as_of 以前でなければ `FutureDataAccessError`（他モジュールの独自キャッシュ参照の門番）."""
        if date > self.as_of:
            raise FutureDataAccessError(f"{self.as_of} 時点で {date} のデータは参照できません")

    def history(self, code: str, *, lookback_rows: int | None = None) -> pd.DataFrame:
        """`as_of` 以前の OHLCV（コピー）。未知の銘柄は空 DataFrame."""
        frame = self._store._frame(code)
        if frame is None:
            return pd.DataFrame(columns=_OHLCV_COLUMNS, index=pd.DatetimeIndex([], name="Date"), dtype=float)
        end = int(frame.index.searchsorted(self._as_of_ts, side="right"))
        start = max(0, end - lookback_rows) if lookback_rows is not None else 0
        return frame.iloc[start:end].copy()

    def bars_on(self, date: str) -> list[dict[str, object]]:
        """`date`（<= as_of）の全銘柄バー。ランキング計算の入力形式（J-Quants 生フィールド名）."""
        self.assert_visible(date)
        frame = self._store._bars(date)
        return [] if frame is None else frame.to_dict("records")

    def closes_on(self, date: str) -> pd.Series:
        """`date`（<= as_of）の全銘柄終値（index = J-Quants 5 桁コード）."""
        self.assert_visible(date)
        frame = self._store._bars(date)
        return pd.Series(dtype=float) if frame is None else frame["AdjC"].astype(float)

    def previous_trading_date(self, date: str) -> str | None:
        self.assert_visible(date)
        return self._store.previous_trading_date(date)

    def trading_dates_until_as_of(self) -> list[str]:
        return self._store.trading_dates_between("0000-00-00", self.as_of)
