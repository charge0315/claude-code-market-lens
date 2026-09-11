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
from collections.abc import AsyncIterator
from typing import Literal

from fastapi import APIRouter, Query
from fastapi.responses import StreamingResponse

from backend.models.common import ApiResponse
from backend.services.db.inference_trace_db import list_recent_runs, list_trace_events
from backend.services.inference.snapshot import build_snapshot

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/inference", tags=["inference"])

_POLL_INTERVAL_SECONDS = 1.0
# ハング防止の安全装置（6 ステージ × LLM 呼び出しを含めても数十秒で終わる想定）。
_STREAM_TIMEOUT_SECONDS = 300.0


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
