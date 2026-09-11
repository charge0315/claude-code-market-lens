"""モデルレジストリ関連 API（champion/challenger・昇格ゲート・PSI ドリフト）.

`plans/03_システム設計` §2.4。昇格は**人手承認 API 経由でのみ**行う
（`POST /promotions/{id}/apply`。自動昇格は既定 OFF、CLAUDE.md）。
"""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Query
from pydantic import BaseModel

from backend.models.common import ApiResponse
from backend.services.db.drift_db import list_drift_snapshots
from backend.services.db.model_registry_db import list_champions, list_promotions
from backend.services.learning.pool_model import POOL_LANE
from backend.services.registry.promotion import apply_promotion, evaluate_ml_pool_promotion, evaluate_promotion

router = APIRouter(prefix="/api/registry", tags=["registry"])


class EvaluatePromotionRequest(BaseModel):
    """`POST /api/registry/promotions/evaluate` のリクエストボディ.

    `lane="ml_pool"`（断面プール分類器、P5d）は held-out 検証指標で判定するため
    `horizon_days` を無視する（`evaluate_ml_pool_promotion` 参照）。
    """

    lane: Literal["mid_term", "short_term", "ml_pool"]
    challenger_version: str
    horizon_days: int = 20


@router.get("/champions", response_model=ApiResponse[list[dict]], summary="系統別 champion 一覧")
async def champions() -> ApiResponse[list[dict]]:
    """全系統（lane）の現行 champion を返す."""
    return ApiResponse.ok(await list_champions())


@router.get("/promotions", response_model=ApiResponse[list[dict]], summary="昇格判定ログ")
async def promotions(
    lane: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
) -> ApiResponse[list[dict]]:
    """昇格ゲートの判定履歴を新しい順で返す（`applied` 済みか、提案止まりかも含む）."""
    return ApiResponse.ok(await list_promotions(lane=lane, limit=limit))


@router.post("/promotions/evaluate", response_model=ApiResponse[dict], summary="昇格ゲートを手動評価")
async def evaluate(req: EvaluatePromotionRequest) -> ApiResponse[dict]:
    """challenger を champion と比較し `model_promotions` へ判定を記録する（提案のみ）."""
    if req.lane == POOL_LANE:
        result = await evaluate_ml_pool_promotion(req.challenger_version)
    else:
        result = await evaluate_promotion(req.lane, req.challenger_version, horizon_days=req.horizon_days)
    return ApiResponse.ok(result)


@router.post("/promotions/{promotion_id}/apply", response_model=ApiResponse[dict], summary="昇格を人手承認で適用")
async def apply(promotion_id: str) -> ApiResponse[dict]:
    """`propose_promote` かつ未適用の判定のみ champion を差し替える（唯一の昇格経路）."""
    applied = await apply_promotion(promotion_id)
    if not applied:
        return ApiResponse.fail("適用できません（判定が propose_promote でないか、既に適用済みです）")
    return ApiResponse.ok({"promotion_id": promotion_id, "applied": True})


@router.get("/drift", response_model=ApiResponse[list[dict]], summary="PSI ドリフト履歴")
async def drift(
    feature: str | None = Query(default=None, description="feature_snapshot の dotted path"),
    limit: int = Query(default=200, ge=1, le=1000),
) -> ApiResponse[list[dict]]:
    """特徴量分布ドリフト（PSI）の履歴を古い順で返す（モデルラボの推移グラフ用）."""
    return ApiResponse.ok(await list_drift_snapshots(feature_name=feature, limit=limit))
