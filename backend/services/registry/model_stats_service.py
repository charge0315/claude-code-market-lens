"""銘柄別モデル（P9/P14）の学習状態を可視化するための集計サービス（🆕 P15）.

`model_stats_db` の生クエリ結果 + `_get_ticker_master()`（全銘柄数）を組み合わせ、
モデルラボ「詳細」タブの3つのグラフ（学習カバレッジ・品質分布・学習の推移）向けの
レスポンスを組み立てる。

`model_champions` は系統（lane）ごとに現行 champion 1 行のみを保持する upsert 方式
（`promoted_at` は毎回上書き）のため、「champion 化件数」の過去の時系列は再構築できない
— 学習の推移は `training_batch_runs`（追記専用ログ）から取れる日別学習試行件数のみで
構成し、champion 化の状況は学習カバレッジ（現在の champion 数）で表現する。
"""

from __future__ import annotations

import json
import logging
from collections import defaultdict
from datetime import datetime, timedelta

from backend.models.registry import ModelCoverage, QualityDistribution, TrainingTrendPoint
from backend.services.data.data_fetcher import _get_ticker_master
from backend.services.db import model_stats_db
from backend.services.jst_time import JST
from backend.services.learning.per_ticker_training_service import PER_TICKER_MODEL_TYPES

logger = logging.getLogger(__name__)

_MODEL_TYPE_LABELS: dict[str, str] = {
    "xgboost": "XGBoost",
    "random_forest": "RandomForest",
    "lstm": "LSTM",
    "transformer": "Transformer",
}


def _model_type_from_lane(lane: str) -> str | None:
    """`f"{model_type}:{ticker}"` 形式の lane から model_type を取り出す（既知の4種のみ）."""
    model_type, sep, _ticker = lane.partition(":")
    if sep and model_type in _MODEL_TYPE_LABELS:
        return model_type
    return None


def _as_finite_float(value: object) -> float | None:
    """数値なら float、bool・非数値・NaN/inf は None（グラフ描画に混入させない）."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    f = float(value)
    return f if f == f and abs(f) != float("inf") else None  # NaN は自身と等しくない


async def build_coverage() -> list[ModelCoverage]:
    """モデルタイプ別の学習カバレッジ（学習済み銘柄数・champion数・全銘柄数）を返す."""
    universe_size = len(await _get_ticker_master())
    trained_counts = await model_stats_db.count_trained_tickers_by_model_type()
    champion_rows = await model_stats_db.list_per_ticker_champion_metrics()

    champion_counts: dict[str, int] = defaultdict(int)
    for row in champion_rows:
        model_type = _model_type_from_lane(str(row["lane"]))
        if model_type:
            champion_counts[model_type] += 1

    return [
        ModelCoverage(
            model_type=mt,
            label=_MODEL_TYPE_LABELS[mt],
            universe_size=universe_size,
            trained_count=trained_counts.get(mt, 0),
            champion_count=champion_counts.get(mt, 0),
        )
        for mt in PER_TICKER_MODEL_TYPES
    ]


async def build_quality_distribution() -> list[QualityDistribution]:
    """モデルタイプ別に、現行 champion の品質指標（skill・rmse）の生値リストを返す."""
    champion_rows = await model_stats_db.list_per_ticker_champion_metrics()
    skill_by_type: dict[str, list[float]] = defaultdict(list)
    rmse_by_type: dict[str, list[float]] = defaultdict(list)

    for row in champion_rows:
        model_type = _model_type_from_lane(str(row["lane"]))
        if not model_type:
            continue
        try:
            metrics = json.loads(str(row["val_metrics"]) or "{}")
        except json.JSONDecodeError:
            logger.warning("val_metrics の JSON デコードに失敗しました（lane=%s）", row["lane"])
            continue
        if not isinstance(metrics, dict):
            continue
        skill = _as_finite_float(metrics.get("skill"))
        if skill is not None:
            skill_by_type[model_type].append(skill)
        rmse = _as_finite_float(metrics.get("rmse"))
        if rmse is not None:
            rmse_by_type[model_type].append(rmse)

    return [
        QualityDistribution(
            model_type=mt,
            label=_MODEL_TYPE_LABELS[mt],
            skill_scores=skill_by_type.get(mt, []),
            rmse_scores=rmse_by_type.get(mt, []),
        )
        for mt in PER_TICKER_MODEL_TYPES
    ]


async def build_training_trend(days: int = 30) -> list[TrainingTrendPoint]:
    """直近 `days` 日分の、日別・モデルタイプ別の学習試行件数（成功/失敗）推移を返す."""
    since = (datetime.now(JST).date() - timedelta(days=days)).isoformat()
    rows = await model_stats_db.get_training_counts_by_date(since=since)

    counts: dict[tuple[str, str], dict[str, int]] = defaultdict(lambda: {"completed": 0, "failed": 0})
    for row in rows:
        model_type = str(row["model_type"])
        if model_type not in _MODEL_TYPE_LABELS:
            continue
        key = (str(row["run_date"]), model_type)
        status = str(row["status"])
        n = row["n"]
        if status in ("completed", "failed") and isinstance(n, (int, float)) and not isinstance(n, bool):
            counts[key][status] += int(n)

    return [
        TrainingTrendPoint(
            date=date,
            model_type=model_type,
            trained_count=values["completed"],
            failed_count=values["failed"],
        )
        for (date, model_type), values in sorted(counts.items())
    ]


__all__ = ["build_coverage", "build_quality_distribution", "build_training_trend"]
