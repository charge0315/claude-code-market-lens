"""評価指標 API（CL-3: 成長曲線・較正・エクイティカーブ）.

`plans/03_システム設計` §2.3。
"""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Query

from backend.models.common import ApiResponse
from backend.services.db import eval_db, pick_outcome_db
from backend.services.ledger import eval_metrics as em
from backend.services.ledger.eval_service import run_eval_batch
from backend.services.ledger.weekly_learning_service import build_weekly_learning_summary
from backend.services.registry.factor_weight_service import DEFAULT_HORIZON_DAYS, compute_ic_weights

router = APIRouter(prefix="/api/eval", tags=["eval"])

_Scope = Literal["mid_term", "short_term", "combined"]


@router.get("/growth", response_model=ApiResponse[list[dict]], summary="評価指標の成長曲線")
async def growth(
    scope: _Scope | None = Query(default=None),
    metric: str | None = Query(default=None, description="win_rate / ic / brier / auc / sharpe など"),
    limit: int = Query(default=500, ge=1, le=2000),
) -> ApiResponse[list[dict]]:
    """モデルバージョン別 / scope 別の評価指標時系列（折れ線用）を古い順で返す."""
    return ApiResponse.ok(await eval_db.list_eval_snapshots(scope=scope, metric_name=metric, limit=limit))


@router.get("/calibration", response_model=ApiResponse[dict | None], summary="最新の較正曲線")
async def calibration(
    scope: _Scope = Query(default="combined"),
    horizon: int | None = Query(default=None, description="評価ホライズン（営業日）"),
) -> ApiResponse[dict | None]:
    """予測確度バケット → 実測勝率の点列（Calibration curve）と Brier を返す."""
    return ApiResponse.ok(await eval_db.get_latest_calibration_curve(scope=scope, horizon_days=horizon))


@router.get("/equity-curve", response_model=ApiResponse[dict], summary="ピック累積成績（エクイティカーブ）")
async def equity_curve(
    scope: _Scope = Query(default="combined"),
    horizon: int = Query(default=20, ge=1, le=60),
) -> ApiResponse[dict]:
    """決着済みピックの超過リターンを勝敗確定順に累積したエクイティカーブと成績サマリを返す."""
    rows = await pick_outcome_db.list_resolved_for_eval(horizon_days=horizon)
    if scope != "combined":
        rows = [r for r in rows if r["horizon_type"] == scope]

    def _f(v: object) -> float:
        return float(v) if isinstance(v, (int, float)) else 0.0

    excess = [_f(r["excess_return"]) for r in rows]
    realized = [_f(r["realized_return"]) for r in rows]
    eq = em.equity_curve(excess)
    return ApiResponse.ok(
        {
            "scope": scope,
            "horizon_days": horizon,
            "n": len(rows),
            "equity": eq,
            "max_drawdown": em.max_drawdown(eq),
            "sharpe": em.sharpe_ratio(realized),
            "win_rate": round(sum(1 for r in rows if r["win"]) / len(rows), 4) if rows else None,
        }
    )


@router.post("/run", response_model=ApiResponse[dict], summary="評価指標の集計を手動実行")
async def run() -> ApiResponse[dict]:
    """全 scope × 主要ホライズンの評価指標を算出・永続化する（通常は beat が夜間に実行）."""
    return ApiResponse.ok(await run_eval_batch())


@router.get("/factor-weights", response_model=ApiResponse[dict], summary="ファクター実測 IC の重み（shadow）")
async def factor_weights(
    horizon_days: int = Query(default=DEFAULT_HORIZON_DAYS, ge=1, le=60),
) -> ApiResponse[dict]:
    """`recommender.FACTOR_WEIGHTS`（本番使用）と実測 |IC| 比例の重み（shadow）を並べて返す.

    shadow 側はここでは一切合成へ反映されない参考値（`services/registry/factor_weight_service`）。
    """
    from backend.services.scoring.recommender import FACTOR_WEIGHTS

    shadow = await compute_ic_weights(horizon_days=horizon_days)
    data = {"horizon_days": horizon_days, "production_weights": FACTOR_WEIGHTS, "shadow_weights": shadow}
    return ApiResponse.ok(data)


@router.get("/weekly-learning", response_model=ApiResponse[dict], summary="週次学習差分サマリ")
async def weekly_learning(
    window_days: int = Query(default=7, ge=1, le=90),
) -> ApiResponse[dict]:
    """直近 `window_days` 日の評価指標差分・昇格判定・ドリフト検知のロールアップを返す."""
    return ApiResponse.ok(await build_weekly_learning_summary(window_days=window_days))
