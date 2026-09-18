"""PIT（point-in-time）特徴量の断面パネルへの as-of backward 結合（🆕 P29）.

`plans/03_システム設計` §3.7.3。**この結合の唯一かつ絶対の不変条件**: ある学習行
`(date, code)` に結合してよいのは `snapshot_date <= date` を満たす直近の PIT 行だけであり、
`snapshot_date > date` の行が結合対象へ混入することは**構造的に**あってはならない
（Vault `Tickers/*.md` の「現在値」を過去の学習行へ broadcast すると未来情報が漏れる —
`plans/04_タスクリスト.md` P29 の完了条件 (2)）。`pandas.merge_asof(direction="backward")`
はこの不変条件をライブラリレベルで保証する（`on` キーが左側の値を超える右側の行とは
決してマッチしない）ため、本モジュールは独自の突き合わせロジックを書かず必ずこれを使う。

被覆率ゲート（PIT 台帳が十分貯まるまで学習投入しない判断）は呼び出し側
（`panel_feature_service.build_panel`）の責務。本モジュールは「結合できたら結合する」
だけで、投入可否は判定しない。
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from backend.services.db import pit_snapshot_db


# tolerance は営業日単位（`config.settings.pit_asof_tolerance_bdays`）だが、`merge_asof` の
# tolerance は暦日でしか指定できない。週末を跨ぐぶんの余裕を持たせ、営業日 N 日 ≈ 暦日
# N*7/5 に切り上げ +1 で近似する（精度より「絶対に未来を跨がない」安全側を優先: 甘めに
# 見積もっても merge_asof の backward 制約自体は緩まないため、too-stale を弾き損ねる方向
# にしか働かない。厳密な営業日カウントは `plans/05_決定ログ` #K で暫定値として明記済み）。
def _tolerance_calendar_days(tolerance_bdays: int) -> int:
    return (tolerance_bdays * 7 + 4) // 5 + 1


FUNDAMENTAL_GROUP = "pit_fundamental"
FUNDAMENTAL_VALUE_COLS: tuple[str, ...] = (
    "per_forecast",
    "pbr",
    "roe",
    "equity_ratio",
    "dividend_yield_forecast",
    "eps_forecast",
    "bps",
    "market_cap_oku",
)
FUNDAMENTAL_STALENESS_COL = "pit_fundamental_staleness_days"
FUNDAMENTAL_HAS_COL = "has_pit_fundamental"

# センチメントは `source` ごとに値列が異なる（keyword は集計スコア1本、llm は判定3値）。
SENTIMENT_VALUE_COLS: dict[str, tuple[str, ...]] = {
    "keyword": ("keyword_score",),
    "llm": ("llm_sentiment_score", "llm_impact_score", "llm_confidence"),
}


def sentiment_group(source: str) -> str:
    return f"pit_sentiment_{source}"


def sentiment_has_col(source: str) -> str:
    return f"has_{sentiment_group(source)}"


def sentiment_staleness_col(source: str) -> str:
    return f"{sentiment_group(source)}_staleness_days"


def _fetch_since_until(dates: pd.Series) -> tuple[str, str]:
    """`dates`（"YYYY-MM-DD" 文字列列）から DB 取得範囲 `[since, until]` を返す（余裕を持たせた since）."""
    min_date = pd.Timestamp(dates.min())
    max_date = pd.Timestamp(dates.max())
    since = (min_date - pd.Timedelta(days=30)).strftime("%Y-%m-%d")
    return since, max_date.strftime("%Y-%m-%d")


def _asof_merge(
    panel: pd.DataFrame, snapshot_rows: list[dict[str, object]], *, value_cols: tuple[str, ...], tolerance_bdays: int
) -> pd.DataFrame:
    """`panel`（`date`/`code` 必須列）へ `snapshot_rows` を as-of backward（`by="code"`）で結合する.

    戻り値は `panel` と**同じ行数・同じ行順**（`_row_pos` で元順序へ復元してから返す — `merge_asof`
    は出力の index を左フレームのものに保存しないため、`(date, code)` の一意性に頼らず明示的に
    復元する）。`snapshot_rows` が空なら全列 NaN（結合対象なしのフェイルソフト、DB 未接続や
    スコープ外の銘柄でも呼び出し元を落とさない）。
    """
    left = panel[["date", "code"]].copy()
    left["_row_pos"] = range(len(left))
    left["_date_ts"] = pd.to_datetime(left["date"])
    left = left.sort_values("_date_ts", kind="mergesort").reset_index(drop=True)

    if not snapshot_rows:
        for col in value_cols:
            left[col] = pd.NA
        left["_matched_snapshot_ts"] = pd.NaT
    else:
        right = pd.DataFrame(snapshot_rows)
        right["_snapshot_ts"] = pd.to_datetime(right["snapshot_date"])
        right = right.sort_values("_snapshot_ts", kind="mergesort").reset_index(drop=True)
        merged = pd.merge_asof(
            left,
            right[["_snapshot_ts", "code", *value_cols]],
            left_on="_date_ts",
            right_on="_snapshot_ts",
            by="code",
            direction="backward",  # 🔒 未来の snapshot と絶対にマッチしない（本モジュールの核心不変条件）
            tolerance=pd.Timedelta(days=_tolerance_calendar_days(tolerance_bdays)),
        )
        left = merged.rename(columns={"_snapshot_ts": "_matched_snapshot_ts"})

    left["data_staleness_days"] = (left["_date_ts"] - left["_matched_snapshot_ts"]).dt.days
    left = left.sort_values("_row_pos", kind="mergesort").reset_index(drop=True)
    return left.drop(columns=["_date_ts", "_matched_snapshot_ts", "_row_pos"])


async def attach_pit_fundamental_features(panel: pd.DataFrame, *, tolerance_bdays: int) -> pd.DataFrame:
    """`panel`（`date`/`code` 列必須）へファンダメンタル PIT 特徴量を as-of backward 結合する.

    入力は変更しない。`per_forecast` 等の生値 + `pit_fundamental_staleness_days` +
    `has_pit_fundamental`（0/1 フラグ、欠損そのものも情報として XGBoost が使えるようにする）
    を追加した新しい DataFrame を返す。staleness 列名はグループ別に namespaced する
    （fundamental / sentiment を両方 attach しても列が衝突しないように）。
    """
    if panel.empty:
        out = panel.copy()
        for col in (*FUNDAMENTAL_VALUE_COLS, FUNDAMENTAL_STALENESS_COL):
            out[col] = pd.Series(dtype="float64")
        out[FUNDAMENTAL_HAS_COL] = pd.Series(dtype="int64")
        return out

    since, until = _fetch_since_until(panel["date"])
    codes = sorted(panel["code"].unique().tolist())
    rows = await pit_snapshot_db.list_fundamental_range(codes=codes, since=since, until=until)

    joined = _asof_merge(panel, rows, value_cols=FUNDAMENTAL_VALUE_COLS, tolerance_bdays=tolerance_bdays)
    joined[FUNDAMENTAL_HAS_COL] = joined["per_forecast"].notna().astype(int)

    out = panel.copy()
    out[FUNDAMENTAL_STALENESS_COL] = joined["data_staleness_days"].to_numpy()
    for col in (*FUNDAMENTAL_VALUE_COLS, FUNDAMENTAL_HAS_COL):
        out[col] = joined[col].to_numpy()
    return out


async def attach_pit_sentiment_features(panel: pd.DataFrame, *, source: str, tolerance_bdays: int) -> pd.DataFrame:
    """`panel` へセンチメント PIT 特徴量（`source="keyword"` / `"llm"`）を as-of backward 結合する."""
    value_cols = SENTIMENT_VALUE_COLS[source]
    has_col = sentiment_has_col(source)
    staleness_col = sentiment_staleness_col(source)

    if panel.empty:
        out = panel.copy()
        for col in (*value_cols, staleness_col):
            out[col] = pd.Series(dtype="float64")
        out[has_col] = pd.Series(dtype="int64")
        return out

    since, until = _fetch_since_until(panel["date"])
    codes = sorted(panel["code"].unique().tolist())
    rows = await pit_snapshot_db.list_sentiment_range(codes=codes, since=since, until=until, source=source)

    joined = _asof_merge(panel, rows, value_cols=value_cols, tolerance_bdays=tolerance_bdays)
    joined[has_col] = joined[value_cols[0]].notna().astype(int)

    out = panel.copy()
    out[staleness_col] = joined["data_staleness_days"].to_numpy()
    for col in (*value_cols, has_col):
        out[col] = joined[col].to_numpy()
    return out


@dataclass(frozen=True)
class PitCoverage:
    """PIT 特徴量グループ 1 つ分の被覆率（ブートストラップゲート判定用、`plans/03` §3.7.4）."""

    group: str
    covered_days: int
    total_days: int
    covered_ratio: float

    def meets_gate(self, *, min_coverage_days: int, min_coverage_ratio: float) -> bool:
        return self.covered_days >= min_coverage_days and self.covered_ratio >= min_coverage_ratio


def compute_group_coverage(panel: pd.DataFrame, *, group: str, has_col: str) -> PitCoverage:
    """`has_col`（0/1）を基に、パネル全体でのそのグループの被覆率を計算する.

    `covered_days` = そのグループが 1 件でも非欠損な行を持つ `date` のユニーク数。
    `covered_ratio` = パネル全行のうち非欠損行の割合。どちらもゼロ行パネルでは 0 を返す。
    """
    if panel.empty or has_col not in panel.columns:
        return PitCoverage(group=group, covered_days=0, total_days=0, covered_ratio=0.0)
    covered_mask = panel[has_col] == 1
    covered_days = panel.loc[covered_mask, "date"].nunique()
    covered_ratio = float(covered_mask.mean())
    return PitCoverage(
        group=group, covered_days=int(covered_days), total_days=panel["date"].nunique(), covered_ratio=covered_ratio
    )
