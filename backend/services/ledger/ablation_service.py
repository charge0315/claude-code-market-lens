"""ソースアブレーション評価（🆕 P29、`source_ablations` の初実装）.

`plans/03_システム設計` §3.7.6。断面プールモデルの学習パネルから、ある情報源グループ
（`pit_fundamental` / `pit_sentiment_keyword` / `pit_sentiment_llm`）に由来する列（生値 ＋
そこから導出された断面列 `xs_rank_*` / `xs_z_*` / `sector_rel_*` / `sector_rank_*` / `market_*`
も含む）を丸ごと落として再学習し、held-out 指標の差分（除外時 − 全部入り）を記録する。

これが「Vault 由来の特徴量を足して本当に良くなったか」を判定する唯一の客観的材料であり、
`pool_training_service.run_pool_training` が実際に運用へ反映する champion/challenger 判定
（`plans/03_システム設計` §3.3）とは独立した評価専用の学習（本番モデルとして登録しない）。
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime

import pandas as pd

from backend.services.db import source_ablation_db
from backend.services.jst_time import JST
from backend.services.learning import pit_feature_service as pit_fs
from backend.services.learning.pool_training_service import train_pool_model

logger = logging.getLogger(__name__)

# 除外グループ → 生の値列（`plans/03_システム設計` §3.7.7 のスコープに合わせ、本フェーズは
# PIT 由来の3グループのみを対象にする。technical/trend は既存の常時特徴量でグループ分けの
# タグ付けをしていないため対象外 — `plans/05_決定ログ` に将来拡張の余地として残す）。
PIT_ABLATION_GROUPS: dict[str, tuple[str, ...]] = {
    pit_fs.FUNDAMENTAL_GROUP: (*pit_fs.FUNDAMENTAL_VALUE_COLS, pit_fs.FUNDAMENTAL_STALENESS_COL),
    pit_fs.sentiment_group("keyword"): (
        *pit_fs.SENTIMENT_VALUE_COLS["keyword"],
        pit_fs.sentiment_staleness_col("keyword"),
    ),
    pit_fs.sentiment_group("llm"): (*pit_fs.SENTIMENT_VALUE_COLS["llm"], pit_fs.sentiment_staleness_col("llm")),
}

# 断面特徴量エンジニアリング（`panel_feature_service.add_cross_sectional_features`）が
# 生の列名から派生列を作るときの接頭辞。除外グループの列を落とす際、これらの派生列も
# 一緒に落とさないと、派生列経由でその情報源のシグナルが残ってしまいアブレーションの
# 意味が無くなる（例: `per_forecast` を落としても `xs_rank_per_forecast` が残ると漏れる）。
_DERIVED_PREFIXES: tuple[str, ...] = ("xs_rank_", "xs_z_", "sector_rel_", "sector_rank_", "market_")

_METRIC_NAMES: tuple[str, ...] = ("auc", "brier_skill", "decile_spread")


@dataclass(frozen=True)
class AblationRunResult:
    """1 グループ分のアブレーション結果（held-out 指標の除外時 − 全部入り）."""

    excluded_source: str
    dropped_columns: tuple[str, ...]
    baseline_metrics: dict[str, float | str | int]
    excluded_metrics: dict[str, float | str | int]
    deltas: dict[str, float]
    sample_n: int


def _group_columns(panel: pd.DataFrame, base_cols: tuple[str, ...]) -> list[str]:
    """`base_cols` とその派生列のうち、実際に `panel` に存在するものだけを返す."""
    candidates = set(base_cols)
    for prefix in _DERIVED_PREFIXES:
        candidates.update(f"{prefix}{col}" for col in base_cols)
    return [c for c in panel.columns if c in candidates]


def _metric_delta(baseline: dict[str, float | str | int], excluded: dict[str, float | str | int]) -> dict[str, float]:
    deltas: dict[str, float] = {}
    for name in _METRIC_NAMES:
        b = baseline.get(name)
        e = excluded.get(name)
        if (
            isinstance(b, (int, float))
            and not isinstance(b, bool)
            and isinstance(e, (int, float))
            and not isinstance(e, bool)
        ):
            deltas[name] = round(float(e) - float(b), 6)
    return deltas


async def run_source_ablation(panel: pd.DataFrame, *, excluded_source: str, seed: int = 42) -> AblationRunResult | None:
    """1 グループぶんのアブレーションを実行する（対象列がパネルに無ければ `None`、フェイルソフト）.

    `excluded_source` は `PIT_ABLATION_GROUPS` のキーのいずれか。対象列が存在しない
    （= その特徴量グループが被覆率ゲート未達で `build_panel` の時点で落とされている、
    または `PIT_FEATURES_ENABLED=false`）場合は「比較のしようがない」ので静かに `None` を返す
    （エラーにはしない — 学習データが薄い運用初期の既定状態そのものであるため）。
    """
    base_cols = PIT_ABLATION_GROUPS.get(excluded_source)
    if base_cols is None:
        raise ValueError(f"未知のアブレーション対象グループです: {excluded_source}")

    dropped = _group_columns(panel, base_cols)
    if not dropped:
        logger.info("アブレーション対象列が存在しないためスキップします: %s", excluded_source)
        return None

    _, baseline_metrics = await asyncio.to_thread(train_pool_model, panel, seed=seed)
    excluded_panel = panel.drop(columns=dropped)
    _, excluded_metrics = await asyncio.to_thread(train_pool_model, excluded_panel, seed=seed)

    n_val = baseline_metrics.get("n_val")
    sample_n = int(n_val) if isinstance(n_val, (int, float)) and not isinstance(n_val, bool) else 0
    return AblationRunResult(
        excluded_source=excluded_source,
        dropped_columns=tuple(dropped),
        baseline_metrics=baseline_metrics,
        excluded_metrics=excluded_metrics,
        deltas=_metric_delta(baseline_metrics, excluded_metrics),
        sample_n=sample_n,
    )


async def run_all_pit_ablations(panel: pd.DataFrame, *, seed: int = 42) -> list[AblationRunResult]:
    """PIT 由来の全グループについてアブレーションを実行し、結果を `source_ablations` へ記録する.

    グループごとに独立して失敗しうる（ラベル不足等の `ValueError`）ため、1 グループの失敗で
    残りを止めない（フェイルソフト、週次フル再学習・昇格ゲートと同じ運用方針）。
    """
    now = datetime.now(JST)
    quarter = f"{now.year}Q{(now.month - 1) // 3 + 1}"
    computed_at = now.isoformat(timespec="seconds")

    results: list[AblationRunResult] = []
    for group in PIT_ABLATION_GROUPS:
        try:
            result = await run_source_ablation(panel, excluded_source=group, seed=seed)
        except ValueError as exc:
            logger.warning("アブレーション評価に失敗しました（%s）: %s", group, exc)
            continue
        if result is None:
            continue
        results.append(result)
        for metric_name, delta in result.deltas.items():
            await source_ablation_db.insert_ablation(
                computed_at=computed_at,
                quarter=quarter,
                excluded_source=group,
                metric_name=metric_name,
                metric_delta=delta,
                sample_n=result.sample_n,
            )
    return results
