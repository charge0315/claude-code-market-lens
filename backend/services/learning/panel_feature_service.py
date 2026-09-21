"""断面プール型モデル（P5d）の特徴量パネル生成.

Market Lens `backend/services/panel_feature_service.py` から移植。変更点:
- `_get_ticker_master` / `get_stock_data` / `jquants` / `JQuantsError` / `calc_target_date` は
  Alpha Forge の既存モジュール（`services/data/data_fetcher.py` 等）を参照するようインポート元を
  変更した（シグネチャは同一）。
- `_build_raw_universe_frame` は `build_feature_matrix` を `predict_mode=True` で呼ぶ（🔧）。
  Market Lens は `predict_mode=False`（既定）のまま呼んでいたため、`build_feature_matrix` の
  ターゲット起因の dropna で直近 `forecast_horizon` 日分の行が失われ、本番当日の推論行が
  `build_panel_context` から欠落し得た。本モジュールはラベルを常に `pool_labeling` から得て
  `build_feature_matrix` の y を使わないため、`predict_mode=True`（特徴量のみで dropna）へ
  切り替えても学習・推論のどちらにも副作用がない（`services/learning/feature_engineering.py`
  のモジュール docstring 参照）。

1. **断面特徴量**（`add_cross_sectional_features`）: 同一営業日のグループ内でのパーセンタイル
   順位・z 値・セクター相対値。
2. **ticker ターゲットエンコーディング**（`add_ticker_target_encoding`）: 銘柄 ID を K-fold OOF
   のラベル平均へ写す（生 ID は cardinality が高すぎてツリーで扱いにくいため）。

`build_panel` はその I/O 層で、ユニバースを走査して銘柄ごとの価格を読み、per-ticker 特徴量
（`feature_engineering.build_feature_matrix`）を縦結合し、J-Quants の全銘柄一括バーから断面
ランクラベル（`pool_labeling.cross_sectional_label`）を付け、断面化した長パネルを返す。
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import logging
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Final

import numpy as np
import pandas as pd

from backend.config import settings
from backend.models.jquants_raw import coerce_optional_float
from backend.models.stocks import TickerInfo
from backend.services.data.data_fetcher import _get_ticker_master, get_stock_data
from backend.services.data.jquants_client import JQuantsClient, jquants
from backend.services.data.jquants_errors import JQuantsError
from backend.services.learning import pit_feature_service as pit_fs
from backend.services.learning.feature_engineering import build_feature_matrix
from backend.services.learning.pool_labeling import POOL_HORIZON_DAYS, cross_sectional_label
from backend.services.trading_calendar import calc_target_date

logger = logging.getLogger(__name__)

# build_feature_matrix の最小行数（内部で 50 を要求）＋ローリング窓の余裕。
_MIN_HISTORY_ROWS = 80

# 🆕 1銘柄ぶんの価格取得に許す上限秒数。yfinance/curl_cffi 側の timeout=30 引数は
# 実機（Windows）で確認したところハング（curl_cffi の perform() が90秒超えても復帰しない）を
# 確実には防げなかったため、アプリ側でも独立した打ち切りを持つ（`_load_price_with_timeout`）。
# ユニバース全銘柄を逐次走査する構造上、1銘柄がここで詰まると `run_picks` 全体が応答不能になる。
_PRICE_FETCH_TIMEOUT_SECONDS: Final = 20.0

# --- 断面特徴量の既定対象列（build_panel が用意する列名） ---
# 🆕 P29: PIT ファンダメンタル列（per_forecast/pbr/roe/dividend_yield_forecast）を追加。
# 絶対水準より「その日のユニバース内・同セクター内での相対位置」のほうが学習に意味を持つ
# ため（`plans/03_システム設計` §3.7.3）。`add_cross_sectional_features` は存在しない入力列を
# 黙ってスキップするため、`PIT_FEATURES_ENABLED=false`（既定）や被覆率ゲート未達で列が
# 無い場合も安全にスキップされる。
_DEFAULT_RANK_COLS: tuple[str, ...] = (
    "return_lag_1",
    "return_lag_5",
    "sma_20_diff",
    "dollar_volume",
    "per_forecast",
    "pbr",
    "roe",
    "dividend_yield_forecast",
)
_DEFAULT_ZSCORE_COLS: tuple[str, ...] = ("volatility_20",)
_DEFAULT_SECTOR_REL_COLS: tuple[str, ...] = ("return_lag_5", "roe")
_DEFAULT_MARKET_COLS: tuple[str, ...] = ("return_lag_1", "return_lag_5")
_BREADTH_COL = "sma_20_diff"

# ターゲットエンコーディングの平滑化強度。ticker のサンプルが薄いほど global 平均へ寄せる:
#   te = (n * ticker_mean + SMOOTHING * global_mean) / (n + SMOOTHING)
_TE_SMOOTHING = 10.0
_TE_N_FOLDS = 5


def _rank_pct_within(df: pd.DataFrame, group_col: str, value_col: str) -> pd.Series:
    """group_col ごとに value_col のパーセンタイル順位（0〜1、NaN は NaN のまま）を返す."""
    return df.groupby(group_col)[value_col].rank(pct=True)


def _zscore_within(df: pd.DataFrame, group_col: str, value_col: str) -> pd.Series:
    """group_col ごとに value_col の z 値を返す（グループの標準偏差が 0 / NaN なら 0.0）."""

    def _z(s: pd.Series) -> pd.Series:
        std = s.std()
        if not np.isfinite(std) or std == 0.0:
            return pd.Series(0.0, index=s.index)
        return (s - s.mean()) / std

    return df.groupby(group_col)[value_col].transform(_z)


def add_cross_sectional_features(
    panel: pd.DataFrame,
    *,
    date_col: str = "date",
    sector_col: str = "sector",
    rank_cols: Sequence[str] = _DEFAULT_RANK_COLS,
    zscore_cols: Sequence[str] = _DEFAULT_ZSCORE_COLS,
    sector_rel_cols: Sequence[str] = _DEFAULT_SECTOR_REL_COLS,
    market_cols: Sequence[str] = _DEFAULT_MARKET_COLS,
) -> pd.DataFrame:
    """長い形式パネルに断面特徴量を追加した新しい DataFrame を返す（入力は変更しない）.

    追加される列:
    - `xs_rank_<col>`   : その営業日の universe 内パーセンタイル順位（rank_cols）
    - `xs_z_<col>`      : その営業日の universe 内 z 値（zscore_cols）
    - `sector_rel_<col>`: その営業日の同セクター中央値との差（sector_rel_cols）
    - `sector_rank_<col>`: その営業日の同セクター内パーセンタイル順位（sector_rel_cols）
    - `market_<col>`    : その営業日の universe 平均（market_cols、全行同値）
    - `breadth_pos`     : その営業日に `_BREADTH_COL` > 0 の銘柄割合（全行同値）

    存在しない入力列は黙ってスキップする（build_panel の列構成変更に耐えるため）。
    """
    out = panel.copy()
    present = set(out.columns)

    for col in rank_cols:
        if col in present:
            out[f"xs_rank_{col}"] = _rank_pct_within(out, date_col, col)

    for col in zscore_cols:
        if col in present:
            out[f"xs_z_{col}"] = _zscore_within(out, date_col, col)

    if sector_col in present:
        for col in sector_rel_cols:
            if col not in present:
                continue
            sector_median = out.groupby([date_col, sector_col])[col].transform("median")
            out[f"sector_rel_{col}"] = out[col] - sector_median
            out[f"sector_rank_{col}"] = out.groupby([date_col, sector_col])[col].rank(pct=True)

    for col in market_cols:
        if col in present:
            out[f"market_{col}"] = out.groupby(date_col)[col].transform("mean")

    if _BREADTH_COL in present:
        out["breadth_pos"] = out.groupby(date_col)[_BREADTH_COL].transform(lambda s: float((s > 0.0).mean()))

    return out


def _kfold_oof_ticker_means(
    tickers: pd.Series, labels: pd.Series, n_folds: int, global_mean: float, seed: int
) -> pd.Series:
    """train 行に対する K-fold OOF の ticker ラベル平均（平滑化込み）を返す.

    各 fold の行には「その fold を除いた残り」から算出した ticker 平均を割り当てるため、
    自分自身のラベルがエンコーディングに漏れない。
    """
    rng = np.random.default_rng(seed)
    tick_arr = tickers.to_numpy()
    lab_arr = labels.to_numpy()
    n = len(tick_arr)
    fold_id = rng.integers(0, n_folds, size=n)
    out = np.full(n, global_mean, dtype=float)

    frame = pd.DataFrame({"ticker": tick_arr, "label": lab_arr, "fold": fold_id})
    for f in range(n_folds):
        train_part = frame[frame["fold"] != f]
        if train_part.empty:
            continue
        agg = train_part.groupby("ticker")["label"].agg(["mean", "count"])
        smoothed = (agg["count"] * agg["mean"] + _TE_SMOOTHING * global_mean) / (agg["count"] + _TE_SMOOTHING)
        holdout_pos = np.flatnonzero(fold_id == f)
        out[holdout_pos] = pd.Series(tick_arr[holdout_pos]).map(smoothed).fillna(global_mean).to_numpy()

    return pd.Series(out, index=tickers.index)


def add_ticker_target_encoding(
    panel: pd.DataFrame,
    *,
    ticker_col: str = "code",
    label_col: str = "label",
    train_mask: pd.Series | None = None,
    n_folds: int = _TE_N_FOLDS,
    seed: int = 42,
) -> pd.DataFrame:
    """`ticker_te` 列（銘柄 ID の漏洩防止ターゲットエンコーディング）を追加した DataFrame を返す.

    - `train_mask`（真の行が学習データ）を渡すと、エンコーディング表は train 行だけから作る。
      train 行には K-fold OOF、非 train 行には train 全体の ticker 平均（平滑化込み、
      未知銘柄は global 平均）を割り当てる。
    - `train_mask=None` なら全行を train とみなし全行 K-fold OOF。
    - ラベルが欠損している行は encoding 表の算出から除外する。
    """
    out = panel.copy()
    mask = pd.Series(True, index=out.index) if train_mask is None else train_mask.reindex(out.index).fillna(False)

    label_known = out[label_col].notna()
    fit_rows = out.index[mask & label_known]
    global_mean = float(out.loc[fit_rows, label_col].mean()) if len(fit_rows) else 0.0

    te = pd.Series(global_mean, index=out.index, dtype=float)

    if len(fit_rows):
        te.loc[fit_rows] = _kfold_oof_ticker_means(
            out.loc[fit_rows, ticker_col], out.loc[fit_rows, label_col], n_folds, global_mean, seed
        )

    non_fit_rows = out.index[~(mask & label_known)]
    if len(non_fit_rows) and len(fit_rows):
        agg = out.loc[fit_rows].groupby(ticker_col)[label_col].agg(["mean", "count"])
        smoothed = (agg["count"] * agg["mean"] + _TE_SMOOTHING * global_mean) / (agg["count"] + _TE_SMOOTHING)
        te.loc[non_fit_rows] = out.loc[non_fit_rows, ticker_col].map(smoothed).fillna(global_mean).to_numpy()

    out["ticker_te"] = te
    return out


# ---------------------------------------------------------------------------
# build_panel（I/O 層）
# ---------------------------------------------------------------------------

PriceLoader = Callable[[str], "pd.DataFrame | None"]
ForwardReturnLoader = Callable[[str], "Awaitable[Mapping[str, float]]"]


def _default_price_loader(code: str) -> pd.DataFrame | None:
    """既定の価格ローダー: yfinance/キャッシュ経由の 5 年 OHLCV（取得失敗は None）."""
    try:
        df = get_stock_data(code, period="5y")
    except Exception:  # noqa: BLE001 - パネル生成は1銘柄の取得失敗で全体を落とさない
        logger.debug("build_panel: %s の価格取得に失敗", code, exc_info=True)
        return None
    return df if df is not None and not df.empty else None


def _load_price_with_timeout(price_loader: PriceLoader, code: str) -> pd.DataFrame | None:
    """`price_loader(code)` を独立スレッドで実行し、`_PRICE_FETCH_TIMEOUT_SECONDS` で打ち切る.

    `future.result(timeout=...)` はスレッド自体を停止できないため、ハングした呼び出しは
    バックグラウンドに残る（放置しても yfinance 呼び出し1回ぶん以上のリソースは食わない）。
    使い捨てのシングルワーカー executor を都度生成することで、ある銘柄がハングしても
    次の銘柄の取得がブロックされない（共有 executor だとワーカー枯渇で直列に詰まる）。
    """
    executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)
    try:
        future = executor.submit(price_loader, code)
        return future.result(timeout=_PRICE_FETCH_TIMEOUT_SECONDS)
    except concurrent.futures.TimeoutError:
        logger.warning(
            "build_panel: %s の価格取得が%.0f秒でタイムアウト — スキップ", code, _PRICE_FETCH_TIMEOUT_SECONDS
        )
        return None
    finally:
        executor.shutdown(wait=False)


async def _default_forward_return_loader(as_of: str) -> dict[str, float]:
    """既定の前方リターンローダー: J-Quants 全銘柄一括バーの as_of と +H 営業日の AdjC 比.

    キーは J-Quants の5桁コード。非営業日（空リスト）・取得失敗時は空 dict を返す。
    """
    target = calc_target_date(pd.Timestamp(as_of), POOL_HORIZON_DAYS)
    try:
        start_bars = await jquants.fetch_all_daily_bars(as_of)
        end_bars = await jquants.fetch_all_daily_bars(target)
    except JQuantsError:
        logger.warning("build_panel: %s の一括バー取得に失敗（前方リターンなし）", as_of)
        return {}

    start = {str(b.get("Code") or ""): coerce_optional_float(b.get("AdjC")) for b in start_bars}
    end = {str(b.get("Code") or ""): coerce_optional_float(b.get("AdjC")) for b in end_bars}
    out: dict[str, float] = {}
    for code, s in start.items():
        e = end.get(code)
        if code and s is not None and s > 0.0 and e is not None:
            out[code] = e / s - 1.0
    return out


def _build_raw_universe_frame(
    tickers: Sequence[TickerInfo], wanted_dates: set[str], price_loader: PriceLoader
) -> pd.DataFrame:
    """ユニバース × 対象営業日の「断面化前」長フレーム（per-ticker 特徴量 ＋ `dollar_volume` ＋
    `date` / `code` / `sector`）を返す。取得失敗銘柄は静かにスキップ。

    `wanted_dates` は "YYYY-MM-DD" 文字列の集合。`get_stock_data` の価格インデックスは
    tz-aware（Asia/Tokyo）で来るため、Timestamp 同士の集合照合ではなく日付文字列で突き合わせる。
    """
    frames: list[pd.DataFrame] = []
    for info in tickers:
        df = _load_price_with_timeout(price_loader, info.code)
        if df is None or len(df) < _MIN_HISTORY_ROWS:
            continue
        try:
            feats, _ = build_feature_matrix(df, predict_mode=True)
        except (ValueError, RuntimeError):
            continue

        rows_ts = [ts for ts in feats.index if ts.strftime("%Y-%m-%d") in wanted_dates]
        if not rows_ts:
            continue
        sub = feats.loc[rows_ts].copy()
        sub["dollar_volume"] = [
            (
                (coerce_optional_float(df.loc[ts, "Close"]) or np.nan)
                * (coerce_optional_float(df.loc[ts, "Volume"]) or np.nan)
                if ts in df.index
                else np.nan
            )
            for ts in sub.index
        ]
        sub["date"] = [ts.strftime("%Y-%m-%d") for ts in sub.index]
        sub["code"] = info.code
        sub["sector"] = info.sector or "UNKNOWN"
        frames.append(sub.reset_index(drop=True))

    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


async def build_panel(
    as_of_dates: Sequence[str],
    *,
    universe: Sequence[TickerInfo] | None = None,
    price_loader: PriceLoader = _default_price_loader,
    forward_return_loader: ForwardReturnLoader = _default_forward_return_loader,
) -> pd.DataFrame:
    """`as_of_dates` の各営業日 × ユニバース各銘柄を1行にした断面学習パネルを返す.

    列 = per-ticker 特徴量（`build_feature_matrix`）＋ `dollar_volume` ＋ `date` / `code` /
    `sector` ＋ `add_cross_sectional_features` の断面列 ＋ `label`（当日 universe 内で前方
    `POOL_HORIZON_DAYS` 日リターンが上位 `POOL_TOP_FRACTION` なら 1.0、そうでなければ 0.0、
    前方リターン不明なら NaN）。`ticker_te` は付けない（呼び出し側が train/val 分割込みで付与）。

    I/O 依存（ユニバース・価格・前方リターン）はすべて引数で差し替え可能（単体テストは
    fetcher をモックした小ユニバースで回す）。
    """
    tickers = list(universe) if universe is not None else await _get_ticker_master()
    wanted = sorted({str(d) for d in as_of_dates})
    # ユニバース全銘柄分の価格取得（同期 I/O）をイベントループ上で直接回すと、その間
    # 他の全リクエストが応答不能になる（1銘柄ずつ yfinance/J-Quants を叩くため長時間かかる）。
    panel = await asyncio.to_thread(_build_raw_universe_frame, tickers, set(wanted), price_loader)
    if panel.empty:
        return pd.DataFrame()
    panel["label"] = np.nan
    # 生の前方リターン（ラベルの元）も残す。学習・eval で「上位十分位の実現リターン」を
    # 測るのに使う（decile_return_spread）。ラベル判定には使わない。
    panel["fwd_return"] = np.nan

    for as_of in wanted:
        forward_returns = await forward_return_loader(as_of)
        labels = cross_sectional_label(forward_returns)  # {J-Quants 5桁: 0.0/1.0}
        if not labels:
            continue
        mask = panel["date"] == as_of
        codes = panel.loc[mask, "code"].unique()
        code_to_label = {code: labels.get(JQuantsClient._to_5digit(code)) for code in codes}
        code_to_fwd = {code: forward_returns.get(JQuantsClient._to_5digit(code)) for code in codes}
        panel.loc[mask, "label"] = panel.loc[mask, "code"].map(code_to_label)
        panel.loc[mask, "fwd_return"] = panel.loc[mask, "code"].map(code_to_fwd)

    if settings.pit_features_enabled:
        panel = await _attach_pit_features(panel)

    return add_cross_sectional_features(panel)


async def _attach_pit_features(panel: pd.DataFrame) -> pd.DataFrame:
    """`PIT_FEATURES_ENABLED=true` の時のみ呼ばれる、PIT 特徴量の断面パネルへの結合本体.

    `plans/03_システム設計` §3.7.4（ブートストラップ被覆率ゲート）。グループ（fundamental /
    sentiment keyword / sentiment llm）ごとに独立して判定し、`PIT_MIN_COVERAGE_DAYS` /
    `PIT_MIN_COVERAGE_RATIO` 未満のグループは値列・`has_*` フラグ列ごと落として学習対象から
    除外する（薄い列を無理に食わせると「欠損 = 古い期間」という時間軸そのものを学習して
    しまい、ウォークフォワード評価が楽観側へ壊れるため）。判定結果は
    `panel.attrs["pit_coverage"]` へ記録し、`pool_training_service`（P29e）が
    `model_registry.val_metrics.pit_coverage` へ転記できるようにする。
    """
    tol = settings.pit_asof_tolerance_bdays
    coverage_report: dict[str, dict[str, object]] = {}

    out = await pit_fs.attach_pit_fundamental_features(panel, tolerance_bdays=tol)
    out, coverage_report[pit_fs.FUNDAMENTAL_GROUP] = _apply_coverage_gate(
        out,
        group=pit_fs.FUNDAMENTAL_GROUP,
        has_col=pit_fs.FUNDAMENTAL_HAS_COL,
        value_cols=(*pit_fs.FUNDAMENTAL_VALUE_COLS, pit_fs.FUNDAMENTAL_STALENESS_COL),
    )

    for source in ("keyword", "llm"):
        out = await pit_fs.attach_pit_sentiment_features(out, source=source, tolerance_bdays=tol)
        group = pit_fs.sentiment_group(source)
        out, coverage_report[group] = _apply_coverage_gate(
            out,
            group=group,
            has_col=pit_fs.sentiment_has_col(source),
            value_cols=(*pit_fs.SENTIMENT_VALUE_COLS[source], pit_fs.sentiment_staleness_col(source)),
        )

    out.attrs["pit_coverage"] = coverage_report
    return out


def _apply_coverage_gate(
    panel: pd.DataFrame, *, group: str, has_col: str, value_cols: tuple[str, ...]
) -> tuple[pd.DataFrame, dict[str, object]]:
    """被覆率ゲートを判定し、未達なら `value_cols` + `has_col` を落とした DataFrame を返す."""
    coverage = pit_fs.compute_group_coverage(panel, group=group, has_col=has_col)
    included = coverage.meets_gate(
        min_coverage_days=settings.pit_min_coverage_days, min_coverage_ratio=settings.pit_min_coverage_ratio
    )
    out = panel if included else panel.drop(columns=[*value_cols, has_col])
    report: dict[str, object] = {
        "covered_days": coverage.covered_days,
        "total_days": coverage.total_days,
        "covered_ratio": round(coverage.covered_ratio, 4),
        "included": included,
    }
    return out, report


# ---------------------------------------------------------------------------
# 推論用の断面コンテキスト
# ---------------------------------------------------------------------------

_TE_GLOBAL_KEY: Final[str] = "__global__"


@dataclass(frozen=True)
class PanelContext:
    """ある営業日の universe 全体を断面化済みにした特徴量フレーム（推論用）.

    断面特徴量（xs_rank / xs_z / sector_rel / market / breadth）は「その日の universe の
    分布」が無いと計算できない。ピック生成が **1回あたり1回** `build_panel_context` で
    これを構築し、`build_inference_row(code, ctx)` で銘柄1行を O(1) で取り出す。
    """

    as_of: str
    frame: pd.DataFrame  # code をキーに引ける、断面化済みの1営業日ぶん universe フレーム

    def has(self, code: str) -> bool:
        return code in self.frame.index


async def build_panel_context(
    as_of: str,
    *,
    universe: Sequence[TickerInfo] | None = None,
    price_loader: PriceLoader = _default_price_loader,
) -> PanelContext:
    """`as_of` 営業日の断面化済み universe フレームを構築する（ラベル・前方リターンは持たない）.

    `build_panel` の per-ticker 特徴量抽出（`_build_raw_universe_frame`）を1営業日ぶん再利用し、
    `add_cross_sectional_features` を1回だけ適用する。`code` を index にして返す。
    """
    tickers = list(universe) if universe is not None else await _get_ticker_master()
    # build_panel と同じ理由でスレッドへ逃がす（ユニバース全銘柄分の同期価格取得）。
    raw = await asyncio.to_thread(_build_raw_universe_frame, tickers, {as_of}, price_loader)
    if raw.empty:
        return PanelContext(as_of=as_of, frame=pd.DataFrame().set_index(pd.Index([], name="code")))
    enriched = add_cross_sectional_features(raw)
    return PanelContext(as_of=as_of, frame=enriched.set_index("code"))


def build_inference_row(
    code: str, ctx: PanelContext, *, ticker_te_map: Mapping[str, float] | None = None
) -> pd.DataFrame | None:
    """`ctx` から銘柄 `code` の推論用1行 DataFrame を返す（universe に居なければ None）.

    列は `build_panel` の出力から `label` / `fwd_return` を除いたもの ＋ `ticker_te`。
    `ticker_te` は学習時に保存した per-ticker 平均（`ticker_te_map`、未知銘柄・None は
    `__global__` 値、それも無ければ 0.5）。`code` 列は残す（下流の識別用）。
    """
    if not ctx.has(code):
        return None
    row = ctx.frame.loc[[code]].reset_index()  # code を列へ戻す
    global_te = 0.5
    if ticker_te_map is not None:
        global_te = float(ticker_te_map.get(_TE_GLOBAL_KEY, 0.5))
        row["ticker_te"] = float(ticker_te_map.get(code, global_te))
    else:
        row["ticker_te"] = global_te
    return row


def compute_ticker_te_map(
    panel: pd.DataFrame,
    *,
    ticker_col: str = "code",
    label_col: str = "label",
    train_mask: pd.Series | None = None,
) -> dict[str, float]:
    """学習データの per-ticker 平滑化ラベル平均 `{code: te}` ＋ `{"__global__": global_mean}` を返す.

    `add_ticker_target_encoding` の非 train 行に使う縮約表と同じ式（平滑化 `_TE_SMOOTHING`）。
    推論時（`build_inference_row`）に銘柄の `ticker_te` を引くため、学習側が保存する。
    """
    mask = pd.Series(True, index=panel.index) if train_mask is None else train_mask.reindex(panel.index).fillna(False)
    fit = panel.loc[mask & panel[label_col].notna()]
    if fit.empty:
        return {_TE_GLOBAL_KEY: 0.5}
    global_mean = float(fit[label_col].mean())
    agg = fit.groupby(ticker_col)[label_col].agg(["mean", "count"])
    smoothed = (agg["count"] * agg["mean"] + _TE_SMOOTHING * global_mean) / (agg["count"] + _TE_SMOOTHING)
    out = {str(code): float(v) for code, v in smoothed.items()}
    out[_TE_GLOBAL_KEY] = global_mean
    return out


# ---------------------------------------------------------------------------
# 推論コンテキストの日次キャッシュ
# ---------------------------------------------------------------------------

_context_cache: dict[str, PanelContext] = {}


async def get_cached_panel_context(as_of: str) -> PanelContext:
    """`build_panel_context(as_of)` を「1営業日ぶんだけ」プロセス内キャッシュして返す.

    ピック生成は 1 日 2 回程度の低頻度発火だが、同一プロセス内で複数回呼ばれても
    ユニバース全体の価格を読み直さないよう最小限のキャッシュを持つ（実質 LRU=1）。
    空フレームもそのままキャッシュする（同日中のリトライはユニバース走査を繰り返すだけで
    好転しない）。celery ワーカーのプロセス寿命で、再起動時に作り直す。
    """
    cached = _context_cache.get(as_of)
    if cached is not None:
        return cached
    ctx = await build_panel_context(as_of)
    _context_cache.clear()
    _context_cache[as_of] = ctx
    return ctx
