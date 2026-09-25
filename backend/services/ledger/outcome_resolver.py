"""決着記録（Outcome Resolution）バッチ — 予測台帳のピックを後追いで解決する（CL-2）.

Market Lens `backend/services/pick_outcome_service.py` の後追い解決パターンを Alpha Forge 用に
再設計（🔧）。変更点:
- Market Lens は単一ホライズン。Alpha Forge は **複数ホライズン**（短期 1/2/3、中長期 5/20/60）
  で 1 ピックにつき複数の `pick_outcomes` 行を作る。
- **MFE / MAE**（保有期間中の最大含み益・最大含み損）と **first_hit**（到達順序）、
  **TOPIX 超過リターン**を記録する（`plans/03` §1.2）。

約定モデル（Market Lens 踏襲）:
- 指値買い: issued 翌営業日以降 `_FILL_WINDOW_TDAYS` 営業日以内に安値 <= entry で約定。
  約定単価は min(entry, その日の始値)。窓内に約定しなければ「未約定」決着（realized 0）。
- トリプルバリア: 安値 <= stop / 高値 >= target。同一日両接触は日次足では順序不明のため
  **損切り優先**（保守的、`labeling.first_barrier_touch` と同じ）。
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from datetime import date, datetime

import pandas as pd

from backend.services.data.data_fetcher import fetch_macro_symbol_data, get_stock_data
from backend.services.jst_time import JST
from backend.services.ledger.labeling import first_barrier_touch

logger = logging.getLogger(__name__)

_FILL_WINDOW_TDAYS = 3
_AGE_BUFFER_DAYS = 4
_TRADING_TO_CALENDAR = 7 / 5
_BENCHMARK_SYMBOL = "^N225"  # 超過リターンの基準（指数比較は ^N225 で統一）
_PRICE_PERIOD = "1y"

HORIZON_SETS: dict[str, tuple[int, ...]] = {
    "short_term": (1, 2, 3),
    "mid_term": (5, 20, 60),
}


@dataclass(frozen=True)
class HorizonOutcome:
    """1 ホライズン分の決着結果."""

    horizon_days: int
    realized_return: float
    win: bool
    hit_stop: bool
    hit_target: bool
    first_hit: str  # stop / target / none
    mfe: float
    mae: float
    benchmark_return: float
    excess_return: float


@dataclass(frozen=True)
class ResolveSummary:
    """1 firing 分の実行結果."""

    resolved_picks: int = 0
    written_outcomes: int = 0
    unfilled: int = 0
    failed: int = 0


# --- 純粋関数（I/O 非依存・テスト対象） ---


def _num(value: object) -> float:
    """DB 行の object 値を float へ（非数値は 0.0）."""
    return float(value) if isinstance(value, (int, float)) else 0.0


def _bars_after(bars: pd.DataFrame, day: str) -> pd.DataFrame:
    """index の日付が day より後の行だけを昇順で返す."""
    day_obj = date.fromisoformat(day[:10])
    mask = [ts.date() > day_obj for ts in bars.index]
    return bars.loc[mask].sort_index()


def simulate_fill(bars: pd.DataFrame, issued_day: str, entry: float) -> tuple[str | None, float | None]:
    """翌営業日以降 `_FILL_WINDOW_TDAYS` 営業日以内の指値買い約定を判定する.

    Returns: (fill_date_iso, fill_price) — 窓内に約定しなければ (None, None)。
    """
    window = _bars_after(bars, issued_day).iloc[:_FILL_WINDOW_TDAYS]
    for ts, row in window.iterrows():
        if float(row["Low"]) <= entry:
            return ts.date().isoformat(), min(entry, float(row["Open"]))
    return None, None


def resolve_horizon(
    bars: pd.DataFrame, fill_day: str, fill_price: float, stop: float, target: float, horizon_days: int
) -> tuple[float, bool, bool, str, float, float] | None:
    """約定日翌営業日から horizon_days 営業日ぶんの日次足で決着を判定する.

    Returns: (realized_return, hit_stop, hit_target, first_hit, mfe, mae) か、窓が空なら None。
    mfe / mae は約定単価基準の最大含み益・最大含み損（exit までの範囲）。
    """
    window = _bars_after(bars, fill_day).iloc[:horizon_days]
    if window.empty:
        return None

    highs = window["High"].tolist()
    lows = window["Low"].tolist()
    touch = first_barrier_touch(highs, lows, stop, target)

    if touch is not None:
        idx, reason = touch
        open_ = float(window.iloc[idx]["Open"])
        if reason == "stop_loss":
            exit_price = min(stop, open_)
            hit_stop, hit_target, first_hit = True, False, "stop"
        else:
            exit_price = max(target, open_)
            hit_stop, hit_target, first_hit = False, True, "target"
        span = window.iloc[: idx + 1]
    else:
        exit_price = float(window.iloc[-1]["Close"])
        hit_stop = hit_target = False
        first_hit = "none"
        span = window

    realized = exit_price / fill_price - 1.0
    mfe = float(span["High"].max()) / fill_price - 1.0
    mae = float(span["Low"].min()) / fill_price - 1.0
    return round(realized, 6), hit_stop, hit_target, first_hit, round(mfe, 6), round(mae, 6)


def benchmark_return(bench_bars: pd.DataFrame, fill_day: str, horizon_days: int) -> float:
    """ベンチマーク（^N225）の約定日 → horizon_days 営業日後の終値リターンを返す（取れなければ 0.0）."""
    on_or_before = [ts for ts in bench_bars.index if ts.date() <= date.fromisoformat(fill_day[:10])]
    after = _bars_after(bench_bars, fill_day).iloc[:horizon_days]
    if not on_or_before or after.empty:
        return 0.0
    base = float(bench_bars.loc[sorted(on_or_before)[-1]]["Close"])
    end = float(after.iloc[-1]["Close"])
    return round(end / base - 1.0, 6) if base else 0.0


def horizon_is_mature(issued_at: str, horizon_days: int, today: str) -> bool:
    """issued_at のホライズン horizon_days が「結末確定」とみなせるだけ暦日が経過したか."""
    min_age = math.ceil((_FILL_WINDOW_TDAYS + horizon_days) * _TRADING_TO_CALENDAR) + _AGE_BUFFER_DAYS
    elapsed = (date.fromisoformat(today) - date.fromisoformat(issued_at[:10])).days
    return elapsed >= min_age


def has_due_horizon(horizon_type: str, issued_at: str, written: set[int], today: str) -> bool:
    """まだ書かれていないホライズンのうち、成熟したものが 1 つでもあるか（株価取得前の安価な絞り込み）.

    未約定の決着は約定窓（3 営業日）の成熟で確定できるが、ここでは判定に使わない。約定したかどうかは
    株価を取得するまで分からず、約定済みの中長期ピックを最短ホライズン（5 日）の成熟前に取得しても
    何も書けないため（2026-09-26、これが件数上限を占領して新しいピックが処理されなかった）。
    その分、未約定の中長期ピックの決着は 5 日ホライズンの成熟まで遅れる。
    """
    return any(h not in written and horizon_is_mature(issued_at, h, today) for h in HORIZON_SETS[horizon_type])


def _written_horizons(value: object) -> set[int]:
    """`list_picks_with_missing_outcomes` の `written_horizons`（カンマ区切り or None）を集合にする."""
    if not isinstance(value, str) or not value:
        return set()
    return {int(x) for x in value.split(",")}


def build_outcomes(
    *,
    horizon_type: str,
    issued_at: str,
    entry: float,
    stop: float,
    target: float,
    bars: pd.DataFrame,
    bench_bars: pd.DataFrame,
    today: str | None = None,
) -> tuple[list[HorizonOutcome], str]:
    """1 ピックの成熟したホライズンすべての決着結果を返す。第 2 要素は状態（filled / unfilled / no_data）."""
    today = today or datetime.now(JST).date().isoformat()
    if bars.empty:
        return [], "no_data"

    fill_day, fill_price = simulate_fill(bars, issued_at, entry)
    if fill_day is None or fill_price is None:
        # 窓を過ぎても未約定なら、未約定決着（realized 0）を全ホライズンで確定させる。
        if horizon_is_mature(issued_at, _FILL_WINDOW_TDAYS, today):
            return (
                [
                    HorizonOutcome(h, 0.0, False, False, False, "none", 0.0, 0.0, 0.0, 0.0)
                    for h in HORIZON_SETS[horizon_type]
                ],
                "unfilled",
            )
        return [], "pending"

    out: list[HorizonOutcome] = []
    for h in HORIZON_SETS[horizon_type]:
        if not horizon_is_mature(issued_at, h, today):
            continue
        resolved = resolve_horizon(bars, fill_day, fill_price, stop, target, h)
        if resolved is None:
            continue
        realized, hit_stop, hit_target, first_hit, mfe, mae = resolved
        bench = benchmark_return(bench_bars, fill_day, h)
        out.append(
            HorizonOutcome(
                horizon_days=h,
                realized_return=realized,
                win=realized > 0.0,
                hit_stop=hit_stop,
                hit_target=hit_target,
                first_hit=first_hit,
                mfe=mfe,
                mae=mae,
                benchmark_return=bench,
                excess_return=round(realized - bench, 6),
            )
        )
    return out, "filled"


# --- オーケストレーション（I/O あり） ---


async def resolve_pending(*, max_picks: int = 20, today: str | None = None) -> ResolveSummary:
    """未記録のホライズンが成熟したピックを古い順に最大 `max_picks` 件解決し、未記録分だけ書き込む.

    `max_picks` は株価取得の回数の上限。成熟したホライズンが無いピックは取得前に除外するので、
    まだ答えの出ない古いピックが上限を占領することはない。
    """
    from backend.services.db import pick_outcome_db

    today = today or datetime.now(JST).date().isoformat()
    horizon_count = max(len(hs) for hs in HORIZON_SETS.values())
    candidates = await pick_outcome_db.list_picks_with_missing_outcomes(horizon_count=horizon_count)
    due = [
        (p, _written_horizons(p["written_horizons"]))
        for p in candidates
        if has_due_horizon(str(p["horizon_type"]), str(p["issued_at"]), _written_horizons(p["written_horizons"]), today)
    ][:max_picks]

    summary = ResolveSummary()
    if not due:
        return summary
    bench_bars = _safe_fetch_macro(_BENCHMARK_SYMBOL)

    for p, written in due:
        symbol = str(p["symbol"])
        try:
            bars = get_stock_data(symbol, period=_PRICE_PERIOD)
        except Exception:  # noqa: BLE001 — 1 銘柄の取得失敗はスキップ（fail-soft）
            logger.warning("決着解決: %s の価格取得に失敗", symbol, exc_info=True)
            summary = ResolveSummary(
                summary.resolved_picks, summary.written_outcomes, summary.unfilled, summary.failed + 1
            )
            continue

        outcomes, status = build_outcomes(
            horizon_type=str(p["horizon_type"]),
            issued_at=str(p["issued_at"]),
            entry=_num(p["entry"]),
            stop=_num(p["stop"]),
            target=_num(p["target"]),
            bars=bars,
            bench_bars=bench_bars,
            today=today,
        )
        # 書き済みのホライズンは書き直さない（resolved_at を最初の決着時刻のまま保つ）。
        outcomes = [o for o in outcomes if o.horizon_days not in written]
        if not outcomes:
            continue

        for o in outcomes:
            await pick_outcome_db.upsert_outcome(
                pick_id=str(p["pick_id"]),
                horizon_days=o.horizon_days,
                resolved_at=datetime.now(JST).isoformat(timespec="seconds"),
                realized_return=o.realized_return,
                win=o.win,
                hit_stop=o.hit_stop,
                hit_target=o.hit_target,
                first_hit=o.first_hit,
                mfe=o.mfe,
                mae=o.mae,
                benchmark_return=o.benchmark_return,
                excess_return=o.excess_return,
                confidence_bucket=str(p["confidence_bucket"]),
                direction=str(p["direction"]),
            )
        summary = ResolveSummary(
            resolved_picks=summary.resolved_picks + 1,
            written_outcomes=summary.written_outcomes + len(outcomes),
            unfilled=summary.unfilled + (1 if status == "unfilled" else 0),
            failed=summary.failed,
        )
    return summary


def _safe_fetch_macro(symbol: str) -> pd.DataFrame:
    try:
        return fetch_macro_symbol_data(symbol, period=_PRICE_PERIOD, interval="1d")
    except Exception:  # noqa: BLE001 — ベンチマーク取得失敗時は excess を 0 として続行
        logger.warning("決着解決: ベンチマーク %s の取得に失敗（超過は 0 扱い）", symbol, exc_info=True)
        return pd.DataFrame()
