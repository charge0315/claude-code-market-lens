"""AI 推論トレース API（P6b、VZ-6 / N4）.

`plans/03_システム設計` §2.2。ライブ SSE 配信は `inference_traces` への INSERT をポーリングで
検知する — ピック生成は celery ワーカー、API は FastAPI プロセスと別プロセスで動くため、
プロセス内 pub/sub ではなく DB ポーリングが唯一の簡潔な配信経路になる（🔧、Redis pub/sub 等の
専用配信基盤は導入していない。数百 ms 間隔のポーリングで SSE の即時性要件には十分）。
"""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from collections.abc import AsyncIterator
from typing import Literal

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import StreamingResponse

from backend.models.common import ApiResponse
from backend.models.inference import SandboxTriggerRequest, SandboxTriggerResponse
from backend.models.pick import ShadowPredictionSummary
from backend.services.api_cost import is_daily_limit_exceeded
from backend.services.db.inference_trace_db import list_recent_runs, list_trace_events
from backend.services.db.shadow_prediction_db import list_shadow_predictions_for_run
from backend.services.inference.sandbox import run_sandbox_inference
from backend.services.inference.snapshot import build_snapshot

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/inference", tags=["inference"])

_POLL_INTERVAL_SECONDS = 1.0
# ハング防止の安全装置（6 ステージ × LLM 呼び出しを含めても数十秒で終わる想定）。
_STREAM_TIMEOUT_SECONDS = 300.0

# 🆕 P36: 同一 (symbol, horizon_type) の多重トリガー防止（プロセス内メモリの簡易ガード、
# 再起動でリセットされる前提。単一プロセスの開発運用のため十分）。
_running_sandbox: set[tuple[str, str]] = set()
# `asyncio.create_task` が参照を持たれず GC される事故を防ぐための保持セット
# （公式ドキュメント推奨パターン、完了時に `add_done_callback` で自動的に外す）。
_background_tasks: set[asyncio.Task[None]] = set()


def _shadow_summary(row: dict[str, object]) -> ShadowPredictionSummary:
    """`shadow_predictions` の生行を表示用の `ShadowPredictionSummary` へ変換する
    （`routers/picks.py` の同名ヘルパーと同型 — `pick_id` を扱わない run_id 経由の一覧のため
    ルーターごとに小さく複製する、既存の `_f`/`_date_bounds` 等と同じ慣習）."""
    payload = row["payload"] if isinstance(row["payload"], dict) else {}
    risk_factors = payload.get("risk_factors")
    holding_period = payload.get("holding_period_days")
    return ShadowPredictionSummary(
        shadow_id=str(row["shadow_id"]),
        challenger_version=str(row["challenger_version"]),
        direction=row["direction"],
        entry=float(row["entry"]),  # type: ignore[arg-type]
        stop=float(row["stop"]),  # type: ignore[arg-type]
        target=float(row["target"]),  # type: ignore[arg-type]
        confidence=float(row["confidence"]),  # type: ignore[arg-type]
        reasoning=str(payload["reasoning"]) if payload.get("reasoning") else None,
        risk_factors=[str(r) for r in risk_factors] if isinstance(risk_factors, list) else [],
        holding_period_days=int(holding_period) if isinstance(holding_period, (int, float)) else None,
        issued_at=str(row["issued_at"]),
    )


@router.get("/runs", response_model=ApiResponse[list[dict]], summary="推論実行一覧")
async def runs(
    horizon_type: Literal["mid_term", "short_term"] | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
) -> ApiResponse[list[dict]]:
    """直近の推論実行一覧（run_id ごとの最新状態、新しい順）を返す."""
    return ApiResponse.ok(await list_recent_runs(horizon_type=horizon_type, limit=limit))


@router.get("/{run_id}", response_model=ApiResponse[dict], summary="DAG スナップショット")
async def snapshot(run_id: str) -> ApiResponse[dict]:
    """指定 run の現在のステージ状態（DAG ノードごとの pending/running/done/failed）を返す."""
    events = await list_trace_events(run_id)
    return ApiResponse.ok(build_snapshot(run_id, events))


@router.get("/{run_id}/replay", response_model=ApiResponse[list[dict]], summary="保存トレースの再生")
async def replay(run_id: str) -> ApiResponse[list[dict]]:
    """指定 run の全ステージイベントを stage_seq 順で返す（フロントが同じレンダラで再生する）."""
    return ApiResponse.ok(await list_trace_events(run_id))


async def _event_source(run_id: str) -> AsyncIterator[str]:
    seen_seq = 0
    elapsed = 0.0
    while elapsed < _STREAM_TIMEOUT_SECONDS:
        events = await list_trace_events(run_id)
        new_events = [e for e in events if int(e["stage_seq"]) > seen_seq]  # type: ignore[call-overload]
        for event in new_events:
            seen_seq = max(seen_seq, int(event["stage_seq"]))  # type: ignore[call-overload]
            yield f"data: {json.dumps(event, ensure_ascii=False, default=str)}\n\n"
        if events and str(events[-1]["status"]) != "running":
            yield "event: done\ndata: {}\n\n"
            return
        await asyncio.sleep(_POLL_INTERVAL_SECONDS)
        elapsed += _POLL_INTERVAL_SECONDS
    yield "event: timeout\ndata: {}\n\n"


@router.get("/{run_id}/stream", summary="ライブ SSE 配信")
async def stream(run_id: str) -> StreamingResponse:
    """新規ステージイベントをポーリングで検知し SSE で配信する（run が終端状態に達したら終了）."""
    return StreamingResponse(_event_source(run_id), media_type="text/event-stream")


@router.post(
    "/sandbox",
    response_model=ApiResponse[SandboxTriggerResponse],
    summary="任意銘柄のオンデマンド推論トレースを開始（🆕 P36）",
)
async def trigger_sandbox(req: SandboxTriggerRequest) -> ApiResponse[SandboxTriggerResponse]:
    """`/chart` 画面から任意銘柄（AI ピック対象外も含む）の推論をその場で1回だけ実行する.

    `prediction_ledger`/`pick_pool_snapshots` へは書き込まない「試し打ち」実行
    （`services/inference/sandbox.py` 参照）。LLM 呼び出しを含むため課金が発生する —
    日次コスト上限（`LLM_DAILY_COST_LIMIT_USD`）超過時は 429 を返す。同一銘柄・ホライズンが
    実行中なら 409 を返す（多重トリガーによる二重課金の簡易防止）。実行はバックグラウンドで
    進み、フロントは返った `run_id` で既存の `GET /api/inference/{run_id}/stream` を購読して
    ライブ表示する。
    """
    if await is_daily_limit_exceeded():
        raise HTTPException(status_code=429, detail="本日のLLM利用コスト上限に達したため実行できません")

    key = (req.symbol, req.horizon_type)
    if key in _running_sandbox:
        raise HTTPException(status_code=409, detail="この銘柄は既に推論を実行中です")

    run_id = str(uuid.uuid4())
    _running_sandbox.add(key)

    async def _run() -> None:
        try:
            await run_sandbox_inference(req.symbol, req.horizon_type, run_id=run_id)
        except Exception:  # noqa: BLE001 — バックグラウンドタスクの例外は呼び出し元へ返せないため
            # ログのみ（トレースが途中で止まった状態としてフロントの SSE には反映される）。
            logger.exception("sandbox 推論に失敗しました（symbol=%s run_id=%s）", req.symbol, run_id)
        finally:
            _running_sandbox.discard(key)

    task = asyncio.create_task(_run())
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)

    return ApiResponse.ok(SandboxTriggerResponse(run_id=run_id))


@router.get(
    "/{run_id}/shadow",
    response_model=ApiResponse[list[ShadowPredictionSummary]],
    summary="オンデマンド推論のシャドウ LLM 比較（🆕 P36）",
)
async def sandbox_shadow(run_id: str) -> ApiResponse[list[ShadowPredictionSummary]]:
    """指定 run のシャドウ判定一覧を返す（`services/inference/sandbox.py` が `pick_id=None` で
    記録したもの）。通常ピックの shadow 一覧は `GET /api/picks/{pick_id}` 側を使う。"""
    rows = await list_shadow_predictions_for_run(run_id)
    return ApiResponse.ok([_shadow_summary(r) for r in rows])
