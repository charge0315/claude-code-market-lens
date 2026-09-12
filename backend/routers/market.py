"""市況スナップショット API（ダッシュボード指数ティッカー行、🆕 P13）."""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter

from backend.models.common import ApiResponse
from backend.models.market import MarketSnapshot
from backend.services.data.market_indices_service import get_market_snapshot
from backend.services.jst_time import JST
from backend.services.trading_calendar import market_status_label

router = APIRouter(prefix="/api/market", tags=["market"])


@router.get("/snapshot", response_model=ApiResponse[MarketSnapshot], summary="指数ティッカー行のスナップショット")
async def get_snapshot() -> ApiResponse[MarketSnapshot]:
    """主要指数の現在値・前日比と市況ステータスを返す（取得できない指数はフェイルソフトで除外）."""
    indices = await get_market_snapshot()
    snapshot = MarketSnapshot(
        indices=indices,
        market_status=market_status_label(),
        updated_at=datetime.now(JST).isoformat(timespec="seconds"),
    )
    return ApiResponse.ok(snapshot)
