"""モデルレジストリ・champion/challenger・昇格ゲートのスキーマ.

`plans/03_システム設計` §1.4（N1）。Alpha Forge は P5d（ML predictor スタック導入）まで
per-ticker / 断面プールの学習済みモデルを持たないため、ここでの「モデル」は
`services/picks/pipeline.MODEL_VERSION`（recommender + LLM プロンプトの構成スナップショット）
を指す。将来 xgboost 等の実モデルが増えても同じ `model_registry` テーブルへ
`model_type` を変えて登録すればよい設計にしてある。
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict

PromotionVerdict = Literal["propose_promote", "hold", "reject"]


class ModelRegistryEntry(BaseModel):
    """`model_registry` の 1 行."""

    model_config = ConfigDict(frozen=True)

    version: str
    model_type: str
    ticker: str
    objective: str
    trained_at: str
    artifact_path: str
    val_metrics: dict[str, object]
    feature_list: list[str]


class ChampionEntry(BaseModel):
    """`model_champions` の 1 行（系統ごとの現行 champion）."""

    model_config = ConfigDict(frozen=True)

    lane: str
    champion_version: str
    promoted_at: str
    promoted_by: str


class ModelCoverage(BaseModel):
    """銘柄別モデル（P9/P14）の学習カバレッジ（🆕 P15）— モデルタイプ別に何%学習済みか.

    `yfinance_count`/`jquants_count`（🆕 P17）は、銘柄ごとの最新の学習成功試行が
    採用したデータソースの内訳（`training_batch_runs.data_source`）。
    `last_trained_at`（🆕 P17）はそのモデルタイプで最後に学習が成功した日時。
    """

    model_config = ConfigDict(frozen=True)

    model_type: str
    label: str
    universe_size: int
    trained_count: int
    champion_count: int
    yfinance_count: int = 0
    jquants_count: int = 0
    last_trained_at: str | None = None


class QualityDistribution(BaseModel):
    """銘柄別モデルの現行 champion における品質指標の生値（🆕 P15、ヒストグラム用）.

    ビン分けはフロントエンド側で行う（値は skill/rmse の生リストのみ）。
    """

    model_config = ConfigDict(frozen=True)

    model_type: str
    label: str
    skill_scores: list[float]
    rmse_scores: list[float]


class TrainingTrendPoint(BaseModel):
    """日別・モデルタイプ別の学習試行件数（🆕 P15、学習の推移グラフ用）."""

    model_config = ConfigDict(frozen=True)

    date: str
    model_type: str
    trained_count: int
    failed_count: int


class PromotionEntry(BaseModel):
    """`model_promotions` の 1 行（昇格ゲートの判定ログ）."""

    model_config = ConfigDict(frozen=True)

    promotion_id: str
    lane: str
    challenger_version: str
    champion_version: str | None
    evaluated_at: str
    holdout_delta: float
    calib_regressed: bool
    paper_perf_delta: float
    paper_days: int
    verdict: PromotionVerdict
    applied: bool
    rationale: dict[str, object]
