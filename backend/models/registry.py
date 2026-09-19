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


class PitGroupCoverage(BaseModel):
    """PIT（point-in-time）特徴量 1 グループぶんの収集進捗（🆕 P29）.

    `collected_days` は `pit_fundamental_snapshots` / `pit_sentiment_snapshots` に
    スナップショットが存在するユニーク営業日数（`services/registry/pit_coverage_service.py`）。
    `ready` は学習パネルへの投入可否（`PIT_MIN_COVERAGE_DAYS` を満たすか）の目安であり、
    実際のゲート判定（`panel_feature_service._apply_coverage_gate`）は被覆率
    （`PIT_MIN_COVERAGE_RATIO`）も見るため、こちらは「あと何営業日で条件を満たすか」の
    分かりやすい進捗表示専用（かんたん/詳細タブ共通）。
    """

    model_config = ConfigDict(frozen=True)

    group: str
    label: str
    collected_days: int
    min_coverage_days: int
    remaining_days: int
    ready: bool


class PitCoverageStatus(BaseModel):
    """PIT 特徴量スナップショットの収集進捗一覧（🆕 P29）."""

    model_config = ConfigDict(frozen=True)

    features_enabled: bool
    groups: list[PitGroupCoverage]


class SourceAblationEntry(BaseModel):
    """`source_ablations` の 1 行（🆕 P29、ソース除外時のホールドアウト指標差分）."""

    model_config = ConfigDict(frozen=True)

    ablation_id: str
    computed_at: str
    quarter: str
    excluded_source: str
    metric_name: str
    metric_delta: float
    sample_n: int


TrainingTargetMode = Literal["portfolio", "picked", "all", "custom"]


class TrainingTargetSettingsResponse(BaseModel):
    """`GET/PUT /api/registry/training-settings` のレスポンス（🆕 学習対象設定）."""

    model_config = ConfigDict(frozen=True)

    target_mode: TrainingTargetMode
    max_parallel_workers: int


class TrainingTargetSettingsUpdateRequest(BaseModel):
    """`PUT /api/registry/training-settings` のリクエストボディ（省略項目は現在値を維持）."""

    model_config = ConfigDict(frozen=True)

    target_mode: TrainingTargetMode | None = None
    max_parallel_workers: int | None = None


class TrainingTargetTickerEntry(BaseModel):
    """カスタムリストの登録済み銘柄 1 件（🆕 学習対象設定、銘柄マスタで名称解決済み）."""

    model_config = ConfigDict(frozen=True)

    code: str
    name: str
    sector: str | None
    added_at: str


class TrainingTargetTickersUpdateRequest(BaseModel):
    """`PUT /api/registry/training-target-tickers` のリクエストボディ（全置換）."""

    model_config = ConfigDict(frozen=True)

    codes: list[str]


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
