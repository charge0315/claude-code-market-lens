"""過去日リプレイ学習 API（🆕 P37）.

実行そのものは独立した子プロセス（`services/replay/runs.py`）で行い、ここは起動・停止・再開と
進捗・結果の参照だけを受け持つ。同時に動かせるのは 1 本まで（J-Quants の取得と CPU を
食い合わないように）。
"""

from __future__ import annotations

import datetime
import uuid
from typing import Final

from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict

from backend.models.common import ApiResponse
from backend.services.db import replay_db
from backend.services.jst_time import today_jst
from backend.services.ledger.outcome_resolver import HORIZON_SETS
from backend.services.replay import learning, runs

router = APIRouter(prefix="/api/replay", tags=["replay"])

# J-Quants の日足は約 5 年前まで。これより前を指定しても取得できないので受け付けない。
_EARLIEST_START: Final[datetime.date] = datetime.date(2016, 1, 1)


class ReplayStartRequest(BaseModel):
    """省略時は「昨日まで」の直近 4 年（先頭 1 年は助走用に別途読み込む）."""

    model_config = ConfigDict(frozen=True)

    start_date: datetime.date | None = None
    end_date: datetime.date | None = None


def _validate_range(start: datetime.date, end: datetime.date, today: datetime.date) -> str | None:
    if start >= end:
        return "開始日は終了日より前にしてください"
    if end >= today:
        return "終了日は昨日以前にしてください（当日分は大引け後も確定待ちのため）"
    if start < _EARLIEST_START:
        return f"開始日は {_EARLIEST_START.isoformat()} 以降にしてください（それより前の日足は取得できません）"
    return None


def _with_alive(run: dict[str, object]) -> dict[str, object]:
    return {**run, "is_alive": runs.is_alive(run)}


@router.post("/runs", response_model=ApiResponse[dict], summary="リプレイを開始")
async def start_run(req: ReplayStartRequest) -> ApiResponse[dict]:
    today = datetime.date.fromisoformat(today_jst())
    default_start, default_end = runs.default_dates(today)
    start = req.start_date or datetime.date.fromisoformat(default_start)
    end = req.end_date or datetime.date.fromisoformat(default_end)
    error = _validate_range(start, end, today)
    if error is not None:
        return ApiResponse.fail(error)
    alive = await runs.find_alive_run()
    if alive is not None:
        return ApiResponse.fail(f"リプレイ {alive['run_id']} が実行中です。停止してから開始してください")
    run_id = await runs.create_and_start(start.isoformat(), end.isoformat())
    return ApiResponse.ok({"run_id": run_id, "start_date": start.isoformat(), "end_date": end.isoformat()})


@router.get("/runs", response_model=ApiResponse[list], summary="リプレイ一覧")
async def list_runs() -> ApiResponse[list]:
    return ApiResponse.ok([_with_alive(r) for r in await replay_db.list_runs()])


@router.get("/runs/{run_uuid}", response_model=ApiResponse[dict], summary="リプレイの進捗と結果")
async def get_run(run_uuid: uuid.UUID) -> ApiResponse[dict]:
    run_id = str(run_uuid)
    run = await replay_db.get_run(run_id)
    if run is None:
        return ApiResponse.fail("リプレイが見つかりません")
    # 完了前でも、決着済みの分だけで途中成績を返す（ゲートホライズンのみ・軽量）。
    live: dict[str, object] = {}
    for horizon_type in HORIZON_SETS:
        gate = learning.GATE_HORIZONS[horizon_type]
        rows = [
            r for r in await replay_db.list_resolved(run_id, horizon_days=gate) if r["horizon_type"] == horizon_type
        ]
        live[horizon_type] = {"horizon_days": gate, "performance": learning.performance_stats(rows)}
    return ApiResponse.ok(
        {
            "run": _with_alive(run),
            "pick_counts": await replay_db.count_picks(run_id),
            "retrains": await replay_db.list_retrains(run_id),
            "live": live,
        }
    )


@router.post("/runs/{run_uuid}/stop", response_model=ApiResponse[dict], summary="リプレイを停止（その日の処理後）")
async def stop_run(run_uuid: uuid.UUID) -> ApiResponse[dict]:
    run_id = str(run_uuid)
    run = await replay_db.get_run(run_id)
    if run is None or not runs.is_alive(run):
        return ApiResponse.fail("実行中のリプレイではありません")
    await replay_db.update_run(run_id, status="stopping")
    return ApiResponse.ok({"run_id": run_id, "status": "stopping"})


@router.post(
    "/runs/{run_uuid}/resume", response_model=ApiResponse[dict], summary="停止・失敗したリプレイを続きから再開"
)
async def resume_run(run_uuid: uuid.UUID) -> ApiResponse[dict]:
    run_id = str(run_uuid)
    run = await replay_db.get_run(run_id)
    if run is None:
        return ApiResponse.fail("リプレイが見つかりません")
    if runs.is_alive(run):
        return ApiResponse.fail("このリプレイはまだ実行中です")
    if run.get("status") == "completed":
        return ApiResponse.fail("完了済みのリプレイです")
    alive = await runs.find_alive_run()
    if alive is not None:
        return ApiResponse.fail(f"リプレイ {alive['run_id']} が実行中です")
    await runs.resume(run_id)
    return ApiResponse.ok({"run_id": run_id, "status": "pending"})
