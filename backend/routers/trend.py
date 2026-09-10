"""最新トレンド（Trend Tracking Agent）API.

ピックパイプラインは `services/data/trend/context.render_trend_context` で内部利用するが、
UI（モデルラボ / 銘柄詳細）からも参照できるよう読み取りエンドポイントを公開する。
`POST /api/trend/sync` は手動同期（LLM を呼ぶためコストに注意。既定は beat 任せ）。
"""

from __future__ import annotations

from fastapi import APIRouter

from backend.models.common import ApiResponse
from backend.models.trend_tracking import TrendSnapshot
from backend.services.data.trend import sync_service

router = APIRouter(prefix="/api/trend", tags=["trend"])


@router.get("", response_model=ApiResponse[TrendSnapshot | None], summary="最新トレンドスナップショット")
async def latest() -> ApiResponse[TrendSnapshot | None]:
    """永続化済みの最新トレンドスナップショットを返す（無ければ data=None）."""
    return ApiResponse.ok(await sync_service.get_latest())


@router.post("/sync", response_model=ApiResponse[TrendSnapshot], summary="トレンドを手動同期")
async def sync(force: bool = False) -> ApiResponse[TrendSnapshot]:
    """収集 → LLM 構造化 → 永続化を実行する（TTL 内は再利用。`force=true` で強制）."""
    return ApiResponse.ok(await sync_service.sync_trends(force=force))
