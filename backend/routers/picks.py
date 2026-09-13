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
from backend.models.pick import (
    GeminiPickSummary,
    PickDetailResponse,
    PickRunResult,
    PickSummary,
    ShadowPredictionSummary,
    SubScores,
)
from backend.services.data.data_fetcher import get_company_name
from backend.services.data.quote_service import compute_change_pct, fetch_quote
from backend.services.db.shadow_prediction_db import list_shadow_predictions_for_pick
from backend.services.ledger import prediction_ledger as pl
from backend.services.picks.gemini_picks import list_gemini_picks
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


def _f(value: object) -> float:
    """DB 生行（`dict[str, object]`）の数値カラムを float へ変換する."""
    return float(value) if isinstance(value, int | float) and not isinstance(value, bool) else 0.0


def _shadow_summary(row: dict[str, object]) -> ShadowPredictionSummary:
    """`shadow_predictions` の生行（🆕 P12）を表示用の `ShadowPredictionSummary` へ変換する."""
    payload = row["payload"] if isinstance(row["payload"], dict) else {}
    risk_factors = payload.get("risk_factors")
    holding_period = payload.get("holding_period_days")
    return ShadowPredictionSummary(
        shadow_id=str(row["shadow_id"]),
        challenger_version=str(row["challenger_version"]),
        direction=row["direction"],
        entry=_f(row["entry"]),
        stop=_f(row["stop"]),
        target=_f(row["target"]),
        confidence=_f(row["confidence"]),
        reasoning=str(payload["reasoning"]) if payload.get("reasoning") else None,
        risk_factors=[str(r) for r in risk_factors] if isinstance(risk_factors, list) else [],
        holding_period_days=int(holding_period) if isinstance(holding_period, (int, float)) else None,
        issued_at=str(row["issued_at"]),
    )


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


@router.get("/gemini", response_model=ApiResponse[list[GeminiPickSummary]], summary="Gemini判定によるピック一覧")
async def list_gemini(
    horizon_type: Literal["mid_term", "short_term"] | None = Query(default=None),
    date: str | None = Query(default=None, description="YYYY-MM-DD（省略時は全期間の新しい順）"),
    limit: int = Query(default=50, ge=1, le=200),
) -> ApiResponse[list[GeminiPickSummary]]:
    """Gemini（challenger LLM）の判定を新しい順で返す（公式パイプラインとは別の比較表示用）."""
    lo, hi = _date_bounds(date)
    rows = await list_gemini_picks(horizon_type=horizon_type, issued_from=lo, issued_to=hi, limit=limit)
    return ApiResponse.ok(rows)


@router.post("/run", response_model=ApiResponse[PickRunResult], summary="ピックを手動実行")
async def run(req: RunRequest) -> ApiResponse[PickRunResult]:
    """指定系統のピックを 1 回生成し、台帳化して結果を返す（beat と冪等でない点に注意）."""
    result = await run_picks(req.horizon_type)
    return ApiResponse.ok(result)


@router.get("/{pick_id}", response_model=ApiResponse[PickDetailResponse | None], summary="単一ピック詳細")
async def get_pick_detail(pick_id: str) -> ApiResponse[PickDetailResponse | None]:
    """単一ピックの詳細（`feature_snapshot` を除いた台帳行 + 表示用銘柄名）を返す."""
    raw = await pl.get_pick(pick_id)
    if raw is None:
        return ApiResponse.fail("該当するピックが見つかりません")
    company_name = await get_company_name(str(raw["symbol"]))
    shadow_rows = await list_shadow_predictions_for_pick(pick_id)
    current_price, prev_close = await fetch_quote(str(raw["symbol"]))
    detail = PickDetailResponse(
        pick_id=str(raw["pick_id"]),
        run_id=str(raw["run_id"]),
        issued_at=str(raw["issued_at"]),
        horizon_type=raw["horizon_type"],
        symbol=str(raw["symbol"]),
        company_name=company_name,
        direction=raw["direction"],
        entry=_f(raw["entry"]),
        stop=_f(raw["stop"]),
        target=_f(raw["target"]),
        sub_scores=SubScores(
            technical=_f(raw["sub_score_technical"]),
            trend=_f(raw["sub_score_trend"]),
            fundamental=_f(raw["sub_score_fundamental"]),
            sentiment=_f(raw["sub_score_sentiment"]),
        ),
        composite_score=_f(raw["composite_score"]),
        concordance=_f(raw["concordance"]),
        confidence_raw=_f(raw["confidence_raw"]),
        confidence=_f(raw["confidence"]),
        confidence_bucket=raw["confidence_bucket"],
        rationale_struct=raw["rationale_struct"],
        rationale_text=str(raw["rationale_text"]),
        model_version=str(raw["model_version"]),
        source_contributions=raw["source_contributions"],
        created_at=str(raw["created_at"]),
        shadow_predictions=[_shadow_summary(r) for r in shadow_rows],
        current_price=current_price,
        change_pct=compute_change_pct(current_price, prev_close),
    )
    return ApiResponse.ok(detail)
