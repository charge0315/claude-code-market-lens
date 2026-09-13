"""ポートフォリオ（保有銘柄）CRUD + リスクチェック API.

`plans/03_システム設計` §2.5。認証は未導入（デスクトップ常駐の単一ユーザー前提、CLAUDE.md）。
"""

from __future__ import annotations

import json
import logging

from fastapi import APIRouter, HTTPException, Query

from backend.models.common import ApiResponse
from backend.models.eod_review import EodReview
from backend.models.portfolio import (
    AddHoldingRequest,
    PortfolioSignal,
    PortfolioSignalStatus,
    PortfolioSummary,
    ReportFillRequest,
    SellHistoryEntry,
    SellHoldingRequest,
    UpdateHoldingRequest,
)
from backend.models.risk import PortfolioRiskReport
from backend.services.data.data_fetcher import get_company_name
from backend.services.db.portfolio_db import (
    delete_holding,
    get_holding,
    insert_holding,
    insert_sell_history,
    list_sell_history,
    update_holding,
)
from backend.services.db.portfolio_signal_db import get_signal, list_signals, set_fill_report, set_status
from backend.services.portfolio.eod_review_service import get_latest as get_latest_eod_review
from backend.services.portfolio.eod_review_service import run_eod_review
from backend.services.portfolio.portfolio_service import build_portfolio
from backend.services.portfolio.risk_service import analyze_portfolio_risk
from backend.services.portfolio.signal_service import run_portfolio_monitor

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/portfolio", tags=["portfolio"])


def _i(value: object) -> int:
    return int(value) if isinstance(value, (int, float)) else 0


def _f(value: object) -> float:
    return float(value) if isinstance(value, (int, float)) else 0.0


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
    """指定ロットを削除する（売却記録を残さない取り消し用。売却は `/sell` を使う）."""
    ok = await delete_holding(holding_id)
    if not ok:
        raise HTTPException(status_code=404, detail=f"保有銘柄 {holding_id} が見つかりません")
    return ApiResponse.ok({"holding_id": holding_id})


@router.post("/holdings/{holding_id}/sell", response_model=ApiResponse[SellHistoryEntry], summary="保有銘柄を売却")
async def sell_holding(holding_id: str, req: SellHoldingRequest) -> ApiResponse[SellHistoryEntry]:
    """保有ロットの一部または全部を売却し、履歴（`portfolio_sell_history`）へ記録する（🆕 P26）.

    売却株数が保有株数と同じなら全量売却（ロット削除）、それ未満なら一部売却（残数へ更新）。
    実現損益は売却時点のロットの平均取得単価から計算する。
    """
    holding = await get_holding(holding_id)
    if holding is None:
        raise HTTPException(status_code=404, detail=f"保有銘柄 {holding_id} が見つかりません")

    current_quantity = _i(holding["quantity"])
    if req.quantity > current_quantity:
        raise HTTPException(
            status_code=422, detail=f"売却株数（{req.quantity}）が保有株数（{current_quantity}）を超えています"
        )

    avg_cost = _f(holding["avg_cost"])
    symbol = str(holding["symbol"])
    realized_pnl = (req.sell_price - avg_cost) * req.quantity

    sell_id = await insert_sell_history(
        holding_id=holding_id,
        symbol=symbol,
        quantity=req.quantity,
        avg_cost=avg_cost,
        sell_price=req.sell_price,
        realized_pnl=realized_pnl,
        sold_at=req.sold_at,
        note=req.note,
    )

    if req.quantity == current_quantity:
        await delete_holding(holding_id)
    else:
        await update_holding(holding_id, quantity=current_quantity - req.quantity, avg_cost=avg_cost)

    return ApiResponse.ok(
        SellHistoryEntry(
            sell_id=sell_id,
            holding_id=holding_id,
            symbol=symbol,
            company_name=await get_company_name(symbol),
            quantity=req.quantity,
            avg_cost=avg_cost,
            sell_price=req.sell_price,
            realized_pnl=realized_pnl,
            sold_at=req.sold_at,
            note=req.note,
        )
    )


@router.get("/sell-history", response_model=ApiResponse[list[SellHistoryEntry]], summary="売却履歴一覧")
async def get_sell_history() -> ApiResponse[list[SellHistoryEntry]]:
    """売却履歴を新しい順で返す（🆕 P26）."""
    rows = await list_sell_history()
    name_by_code: dict[str, str | None] = {}
    entries: list[SellHistoryEntry] = []
    for row in rows:
        symbol = str(row["symbol"])
        if symbol not in name_by_code:
            name_by_code[symbol] = await get_company_name(symbol)
        entries.append(
            SellHistoryEntry(
                sell_id=str(row["sell_id"]),
                holding_id=str(row["holding_id"]),
                symbol=symbol,
                company_name=name_by_code[symbol],
                quantity=_i(row["quantity"]),
                avg_cost=_f(row["avg_cost"]),
                sell_price=_f(row["sell_price"]),
                realized_pnl=_f(row["realized_pnl"]),
                sold_at=str(row["sold_at"]),
                note=row["note"] if row["note"] is None else str(row["note"]),
            )
        )
    return ApiResponse.ok(entries)


@router.get("/signals", response_model=ApiResponse[list[PortfolioSignal]], summary="AI 売買タイミング判定一覧")
async def get_signals(
    status: PortfolioSignalStatus | None = Query(default=None),
) -> ApiResponse[list[PortfolioSignal]]:
    """判定履歴（承認キュー）を新しい順で返す."""
    rows = await list_signals(status=status)
    return ApiResponse.ok([PortfolioSignal.model_validate(r) for r in rows])


@router.post("/signals/run", response_model=ApiResponse[dict], summary="保有監視を手動実行")
async def run_signals() -> ApiResponse[dict]:
    """全保有ロットを AI 判定し `portfolio_signals` へ記録する（通常は beat が場中に実行）."""
    signal_ids = await run_portfolio_monitor()
    return ApiResponse.ok({"signal_ids": signal_ids, "count": len(signal_ids)})


@router.post("/signals/{signal_id}/approve", response_model=ApiResponse[dict], summary="判定を承認")
async def approve_signal(signal_id: str) -> ApiResponse[dict]:
    """`proposed` の判定を `approved` にする（人手承認 API 専用）."""
    row = await get_signal(signal_id)
    if row is None:
        raise HTTPException(status_code=404, detail=f"判定 {signal_id} が見つかりません")
    if row["status"] != "proposed":
        detail = f"判定 {signal_id} は proposed 状態ではありません（{row['status']}）"
        raise HTTPException(status_code=409, detail=detail)
    await set_status(signal_id, "approved")
    return ApiResponse.ok({"signal_id": signal_id, "status": "approved"})


@router.post("/signals/{signal_id}/reject", response_model=ApiResponse[dict], summary="判定を却下")
async def reject_signal(signal_id: str) -> ApiResponse[dict]:
    """`proposed` の判定を `rejected` にする."""
    row = await get_signal(signal_id)
    if row is None:
        raise HTTPException(status_code=404, detail=f"判定 {signal_id} が見つかりません")
    if row["status"] != "proposed":
        detail = f"判定 {signal_id} は proposed 状態ではありません（{row['status']}）"
        raise HTTPException(status_code=409, detail=detail)
    await set_status(signal_id, "rejected")
    return ApiResponse.ok({"signal_id": signal_id, "status": "rejected"})


@router.post("/signals/{signal_id}/report-fill", response_model=ApiResponse[dict], summary="実約定結果を報告")
async def report_fill(signal_id: str, req: ReportFillRequest) -> ApiResponse[dict]:
    """`approved` の判定に対し、人間が実際に行った約定結果を報告する（`executed` へ遷移）.

    アプリ自体はブローカー発注を一切行わない（CLAUDE.md）。ここは実約定の事後記録専用。
    """
    row = await get_signal(signal_id)
    if row is None:
        raise HTTPException(status_code=404, detail=f"判定 {signal_id} が見つかりません")
    if row["status"] != "approved":
        detail = f"判定 {signal_id} は approved 状態ではありません（{row['status']}）"
        raise HTTPException(status_code=409, detail=detail)
    await set_fill_report(signal_id, json.dumps(req.model_dump(), ensure_ascii=False))
    return ApiResponse.ok({"signal_id": signal_id, "status": "executed"})


@router.get("/eod-review", response_model=ApiResponse[EodReview | None], summary="大引け後レビュー取得")
async def get_eod_review_endpoint() -> ApiResponse[EodReview | None]:
    """最新の大引け後レビューを返す（1 件も無ければ `data: null`）."""
    return ApiResponse.ok(await get_latest_eod_review())


@router.post("/eod-review/run", response_model=ApiResponse[EodReview], summary="大引け後レビューを手動実行")
async def run_eod_review_endpoint(force: bool = False) -> ApiResponse[EodReview]:
    """本日分のレビューを実行する（通常は beat が 16:31 JST に実行）。既にあれば再利用（`force=true` で再生成）."""
    return ApiResponse.ok(await run_eod_review(force=force))
