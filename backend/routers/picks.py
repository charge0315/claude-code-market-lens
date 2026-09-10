"""AI 銘柄ピック API（中長期 / 短期の 2 系統）.

`plans/03_システム設計` §2.1。すべての売買提案レスポンスは 3 値（entry / stop / target）と
`confidence` を必ず含む（CLAUDE.md）。
"""

from __future__ import annotations

import logging
from typing import Literal

from fastapi import APIRouter, Query
from pydantic import BaseModel

from backend.models.common import ApiResponse
from backend.models.pick import PickRunResult, PickSummary
from backend.services.ledger import prediction_ledger as pl
from backend.services.picks.pipeline import run_picks

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/picks", tags=["picks"])


class RunRequest(BaseModel):
    """`POST /api/picks/run` のリクエストボディ."""

    horizon_type: Literal["mid_term", "short_term"]


def _date_bounds(date: str | None) -> tuple[str | None, str | None]:
    """`YYYY-MM-DD` を issued_at（ISO8601）の下限 / 上限に変換する."""
    if date is None:
        return None, None
    return f"{date}T00:00:00", f"{date}T23:59:59+09:00"


@router.get("/mid-term", response_model=ApiResponse[list[PickSummary]], summary="中長期ピック一覧")
async def list_mid_term(
    date: str | None = Query(default=None, description="YYYY-MM-DD（省略時は全期間の新しい順）"),
    bucket: str | None = Query(default=None, description="確度バケット high/mid/low"),
    limit: int = Query(default=50, ge=1, le=200),
) -> ApiResponse[list[PickSummary]]:
    """中長期ピックを確度・合成スコア順で返す（3 値・根拠・確度バケット付き）."""
    lo, hi = _date_bounds(date)
    rows = await pl.list_picks(horizon_type="mid_term", issued_from=lo, issued_to=hi, bucket=bucket, limit=limit)
    return ApiResponse.ok(rows)


@router.get("/short-term", response_model=ApiResponse[list[PickSummary]], summary="短期（デイトレ）ピック一覧")
async def list_short_term(
    date: str | None = Query(default=None),
    bucket: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
) -> ApiResponse[list[PickSummary]]:
    """短期ピックを確度・合成スコア順で返す."""
    lo, hi = _date_bounds(date)
    rows = await pl.list_picks(horizon_type="short_term", issued_from=lo, issued_to=hi, bucket=bucket, limit=limit)
    return ApiResponse.ok(rows)


@router.post("/run", response_model=ApiResponse[PickRunResult], summary="ピックを手動実行")
async def run(req: RunRequest) -> ApiResponse[PickRunResult]:
    """指定系統のピックを 1 回生成し、台帳化して結果を返す（beat と冪等でない点に注意）."""
    result = await run_picks(req.horizon_type)
    return ApiResponse.ok(result)


@router.get("/{pick_id}", response_model=ApiResponse[dict], summary="単一ピック詳細")
async def get_pick_detail(pick_id: str) -> ApiResponse[dict]:
    """単一ピックの詳細（`feature_snapshot` を除いた台帳行）を返す."""
    raw = await pl.get_pick(pick_id)
    if raw is None:
        return ApiResponse.fail("該当するピックが見つかりません")
    raw.pop("feature_snapshot", None)
    return ApiResponse.ok(raw)
