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
from backend.services.learning.per_ticker_training_service import run_daily_training_batch
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


class TrainingRunRequest(BaseModel):
    """`POST /api/registry/training/run` のリクエストボディ."""

    model_type: Literal["xgboost", "random_forest", "lstm", "transformer"]


def _is_per_ticker_lane(lane: object) -> bool:
    """銘柄別モデル（P9）の lane（`f"{model_type}:{ticker}"`）かどうかを判定する.

    システム全体レーン（`ml_pool`/`mid_term`/`short_term`）は `:` を含まないため、
    `:` の有無だけで一意に判別できる（`per_ticker_training_service._lane` 参照）。
    """
    return isinstance(lane, str) and ":" in lane


@router.get("/champions", response_model=ApiResponse[list[dict]], summary="系統別 champion 一覧")
async def champions() -> ApiResponse[list[dict]]:
    """全系統（lane）の現行 champion を返す.

    銘柄別モデル（P9、`lane=f"{model_type}:{ticker}"`）は品質ゲートで自動承認されるため
    数千件に上りうる。モデルラボの一覧は既存のシステムレーン（ml_pool/mid_term/short_term）
    比較用であり、それが埋もれないよう除外する（`per_ticker_training_service.py` 参照）。
    """
    rows = await list_champions()
    return ApiResponse.ok([r for r in rows if not _is_per_ticker_lane(r.get("lane"))])


@router.get("/promotions", response_model=ApiResponse[list[dict]], summary="昇格判定ログ")
async def promotions(
    lane: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
) -> ApiResponse[list[dict]]:
    """昇格ゲートの判定履歴を新しい順で返す（`applied` 済みか、提案止まりかも含む）.

    銘柄別モデル（P9）は `model_promotions` へ書き込まない（品質ゲートの自動承認は
    `model_champions` を直接差し替えるのみ）ため、本来この一覧に混入することは無いが、
    `champions()` と一貫した安全側のフィルタとして同様に除外する。
    """
    rows = await list_promotions(lane=lane, limit=limit)
    return ApiResponse.ok([r for r in rows if not _is_per_ticker_lane(r.get("lane"))])


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


@router.post("/training/run", response_model=ApiResponse[dict], summary="銘柄別モデルの学習バッチを手動実行")
async def run_training(req: TrainingRunRequest) -> ApiResponse[dict]:
    """指定モデルタイプの日次学習バッチを1回分だけ即時実行する（celery beat と同じ関数、手動トリガー）.

    東証全銘柄のうち当日の上限まで（未学習優先→最も学習が古い順）を学習する
    （`per_ticker_training_service.run_daily_training_batch`）。品質ゲート合格分は
    `model_champions` を自動差し替える（P9、人手承認は不要）。モデルタイプにより
    数十秒〜数分かかりうる（xgboost/random_forest は5分、lstm/transformer は60分の
    1firing予算と同じ時間予算で動く）。
    """
    summary = await run_daily_training_batch(req.model_type)
    return ApiResponse.ok(summary.to_dict())


@router.get("/drift", response_model=ApiResponse[list[dict]], summary="PSI ドリフト履歴")
async def drift(
    feature: str | None = Query(default=None, description="feature_snapshot の dotted path"),
    limit: int = Query(default=200, ge=1, le=1000),
) -> ApiResponse[list[dict]]:
    """特徴量分布ドリフト（PSI）の履歴を古い順で返す（モデルラボの推移グラフ用）."""
    return ApiResponse.ok(await list_drift_snapshots(feature_name=feature, limit=limit))
