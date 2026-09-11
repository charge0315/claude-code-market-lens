"""ポートフォリオ（保有銘柄）CRUD + リスクチェック API.

`plans/03_システム設計` §2.5。認証は未導入（デスクトップ常駐の単一ユーザー前提、CLAUDE.md）。
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException

from backend.models.common import ApiResponse
from backend.models.portfolio import AddHoldingRequest, PortfolioSummary, UpdateHoldingRequest
from backend.models.risk import PortfolioRiskReport
from backend.services.db.portfolio_db import delete_holding, insert_holding, update_holding
from backend.services.portfolio.portfolio_service import build_portfolio
from backend.services.portfolio.risk_service import analyze_portfolio_risk

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/portfolio", tags=["portfolio"])


@router.get("", response_model=ApiResponse[PortfolioSummary], summary="ポートフォリオ取得")
async def get_portfolio() -> ApiResponse[PortfolioSummary]:
    """保有銘柄一覧をリアルタイム株価で時価評価し、P&L・評価損益率を含むサマリーを返す."""
    return ApiResponse.ok(await build_portfolio())


@router.get("/risk", response_model=ApiResponse[PortfolioRiskReport], summary="ポートフォリオのリスクチェック")
async def get_portfolio_risk() -> ApiResponse[PortfolioRiskReport]:
    """セクター集中度・銘柄間相関の警告を返す."""
    return ApiResponse.ok(await analyze_portfolio_risk())


@router.post("/holdings", response_model=ApiResponse[dict], status_code=201, summary="保有銘柄追加")
async def add_holding(req: AddHoldingRequest) -> ApiResponse[dict]:
    """銘柄コード・株数・平均取得単価・取得日を指定して保有ロットを追加する."""
    try:
        holding_id = await insert_holding(
            symbol=req.symbol, quantity=req.quantity, avg_cost=req.avg_cost, acquired_at=req.acquired_at
        )
    except Exception as e:
        logger.warning("保有銘柄の追加に失敗（同一銘柄・同一取得日の重複の可能性）: %s", e)
        raise HTTPException(status_code=409, detail="同一銘柄・同一取得日のロットが既に存在します") from e
    return ApiResponse.ok({"holding_id": holding_id})


@router.put("/holdings/{holding_id}", response_model=ApiResponse[dict], summary="保有銘柄更新")
async def update_holding_endpoint(holding_id: str, req: UpdateHoldingRequest) -> ApiResponse[dict]:
    """指定ロットの株数・平均取得単価を更新する."""
    ok = await update_holding(holding_id, quantity=req.quantity, avg_cost=req.avg_cost)
    if not ok:
        raise HTTPException(status_code=404, detail=f"保有銘柄 {holding_id} が見つかりません")
    return ApiResponse.ok({"holding_id": holding_id})


@router.delete("/holdings/{holding_id}", response_model=ApiResponse[dict], summary="保有銘柄削除")
async def remove_holding(holding_id: str) -> ApiResponse[dict]:
    """指定ロットを削除する."""
    ok = await delete_holding(holding_id)
    if not ok:
        raise HTTPException(status_code=404, detail=f"保有銘柄 {holding_id} が見つかりません")
    return ApiResponse.ok({"holding_id": holding_id})
