"""モデルレジストリ関連 API（champion/challenger・昇格ゲート・PSI ドリフト）.

`plans/03_システム設計` §2.4。昇格は**人手承認 API 経由でのみ**行う
（`POST /promotions/{id}/apply`。自動昇格は既定 OFF、CLAUDE.md）。
"""

from __future__ import annotations

import asyncio
import logging
from typing import Literal

from fastapi import APIRouter, Query
from pydantic import BaseModel

from backend.models.common import ApiResponse
from backend.services.db.drift_db import list_drift_snapshots
from backend.services.db.model_registry_db import list_champions, list_promotions
from backend.services.db.training_batch_db import get_attempted_tickers
from backend.services.jst_time import today_jst
from backend.services.learning.per_ticker_training_service import (
    ModelType,
    manual_full_run_overrides,
    run_daily_training_batch,
)
from backend.services.learning.pool_model import POOL_LANE
from backend.services.registry.promotion import apply_promotion, evaluate_ml_pool_promotion, evaluate_promotion

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/registry", tags=["registry"])

# 銘柄別モデルの日次学習バッチ（🔧 P13h）: モデルタイプごとに数十秒〜10分かかりうるため、
# HTTP リクエスト内で同期 await すると（Next.js の rewrite プロキシ等、経路上のどこかの
# タイムアウトに引っかかり）ブラウザ側には失敗と映る一方、バックエンド側はそのまま処理を
# 続行してしまう（実際に学習・champion 化は成立するのに UI が「失敗」と表示する不整合が
# 発生した）。バックグラウンドタスクとして起動し即座に応答を返す方式へ変更し、進捗・結果は
# `GET /training/status` でポーリングする。`model_promotions` を介さない自動承認ガバナンス
# （P9）という位置づけ自体は変えない。
_running_batches: dict[ModelType, asyncio.Task[None]] = {}
_last_results: dict[ModelType, dict[str, object]] = {}


async def _run_and_record(model_type: ModelType) -> None:
    """バックグラウンドで学習バッチを実行し、結果を `_last_results` へ記録する.

    手動トリガーは「いけるところまでいく」（🆕 P14、ユーザー確認済み）ため
    `manual_full_run_overrides` の上限を使う。celery-beat の自動定期実行
    （`tasks.py`）はこれを経由せず既存の上限のまま変更しない。
    """
    daily_limit, max_duration = manual_full_run_overrides(model_type)
    try:
        summary = await run_daily_training_batch(
            model_type, daily_limit_override=daily_limit, max_duration_override=max_duration
        )
        _last_results[model_type] = {**summary.to_dict(), "error": None}
    except Exception as e:  # noqa: BLE001 — バックグラウンドタスクの想定外エラーを UI 側へ伝える
        logger.exception("学習バッチが異常終了しました（model_type=%s）", model_type)
        _last_results[model_type] = {"model_type": model_type, "error": str(e)}
    finally:
        _running_batches.pop(model_type, None)


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


@router.post("/training/run", response_model=ApiResponse[dict], summary="銘柄別モデルの学習バッチを起動")
async def run_training(req: TrainingRunRequest) -> ApiResponse[dict]:
    """指定モデルタイプの日次学習バッチをバックグラウンドで起動し、即座に応答する（🔧 P13h）.

    東証全銘柄のうち当日の上限まで（未学習優先→最も学習が古い順）を学習する
    （`per_ticker_training_service.run_daily_training_batch`）。品質ゲート合格分は
    `model_champions` を自動差し替える（P9、人手承認は不要）。モデルタイプにより
    数十秒〜数分かかりうる（xgboost/random_forest は5分、lstm/transformer は60分の
    1firing予算と同じ時間予算で動く）ため、完了を待たず即時に `started` を返す。
    進捗・結果は `GET /training/status` をポーリングして確認する。
    """
    model_type = req.model_type
    if model_type in _running_batches:
        return ApiResponse.ok({"model_type": model_type, "status": "already_running"})
    _last_results.pop(model_type, None)
    task = asyncio.create_task(_run_and_record(model_type))
    _running_batches[model_type] = task
    return ApiResponse.ok({"model_type": model_type, "status": "started"})


@router.get("/training/status", response_model=ApiResponse[dict], summary="銘柄別モデル学習バッチの進捗・結果")
async def training_status(
    model_type: Literal["xgboost", "random_forest", "lstm", "transformer"] = Query(...),
) -> ApiResponse[dict]:
    """指定モデルタイプの学習バッチが実行中かどうか・本日ここまでの試行件数・直近の結果を返す.

    `TrainingTriggerPanel`（🔧 P13h）が `POST /training/run` 後にポーリングする想定。
    """
    running = model_type in _running_batches
    attempted_today = len(await get_attempted_tickers(today_jst(), model_type))
    return ApiResponse.ok(
        {
            "model_type": model_type,
            "running": running,
            "attempted_today": attempted_today,
            "last_result": _last_results.get(model_type),
        }
    )


@router.get("/drift", response_model=ApiResponse[list[dict]], summary="PSI ドリフト履歴")
async def drift(
    feature: str | None = Query(default=None, description="feature_snapshot の dotted path"),
    limit: int = Query(default=200, ge=1, le=1000),
) -> ApiResponse[list[dict]]:
    """特徴量分布ドリフト（PSI）の履歴を古い順で返す（モデルラボの推移グラフ用）."""
    return ApiResponse.ok(await list_drift_snapshots(feature_name=feature, limit=limit))
