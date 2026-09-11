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
