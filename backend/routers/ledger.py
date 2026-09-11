"""予測台帳・決着記録 API（CL-1 / CL-2）.

`plans/03_システム設計` §2.3。
"""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Query

from backend.models.common import ApiResponse
from backend.models.pick import PickSummary
from backend.services.db import pick_outcome_db
from backend.services.ledger import outcome_resolver
from backend.services.ledger import prediction_ledger as pl

router = APIRouter(prefix="/api/ledger", tags=["ledger"])


@router.get("", response_model=ApiResponse[list[PickSummary]], summary="予測台帳の検索")
async def search_ledger(
    horizon: Literal["mid_term", "short_term"] | None = Query(default=None),
    from_date: str | None = Query(default=None, alias="from", description="issued_at 下限 YYYY-MM-DD"),
    to_date: str | None = Query(default=None, alias="to"),
    bucket: str | None = Query(default=None, description="確度バケット high/mid/low"),
    limit: int = Query(default=100, ge=1, le=500),
) -> ApiResponse[list[PickSummary]]:
    """条件に合うピックを新しい順で返す（`feature_snapshot` は含めない）."""
    lo = f"{from_date}T00:00:00" if from_date else None
    hi = f"{to_date}T23:59:59+09:00" if to_date else None
    rows = await pl.list_picks(horizon_type=horizon, issued_from=lo, issued_to=hi, bucket=bucket, limit=limit)
    return ApiResponse.ok(rows)


@router.get("/{pick_id}/outcomes", response_model=ApiResponse[list[dict]], summary="ピックの決着記録")
async def pick_outcomes(pick_id: str) -> ApiResponse[list[dict]]:
    """指定ピックの決着行（複数ホライズン: 短期 1/2/3、中長期 5/20/60）を返す."""
    return ApiResponse.ok(await pick_outcome_db.list_outcomes(pick_id))


@router.post("/resolve", response_model=ApiResponse[dict], summary="決着記録を手動実行")
async def resolve(max_picks: int = Query(default=20, ge=1, le=100)) -> ApiResponse[dict]:
    """未決着のピックを古い順に解決して `pick_outcomes` へ書き込む（通常は beat が夜間に実行）."""
    summary = await outcome_resolver.resolve_pending(max_picks=max_picks)
    return ApiResponse.ok(
        {
            "resolved_picks": summary.resolved_picks,
            "written_outcomes": summary.written_outcomes,
            "unfilled": summary.unfilled,
            "failed": summary.failed,
        }
    )
