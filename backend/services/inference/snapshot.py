"""推論トレースの DAG スナップショット構築（純関数、P6b）.

`inference_traces` は各ステージの完了/失敗のみを記録する append-only ログで、専用の
「実行中」行は持たない（P6a `orchestrator._Recorder` は stage_seq ごとに1行だけ INSERT する）。
そのため run 全体がまだ `running` のときは、最後に完了したステージの次を「推定 running」として
見せる（`STAGE_ORDER` 上の次ステージ。実際にそのステージが動いているかは保証しないが、
6 ステージが数百ms〜数秒で逐次進む前提では実用上十分な近似）。
"""

from __future__ import annotations

from typing import cast

from backend.models.inference import STAGE_ORDER, StageName


def build_snapshot(run_id: str, events: list[dict[str, object]]) -> dict[str, object]:
    """`inference_trace_db.list_trace_events` の結果から DAG スナップショットを返す.

    `stages` は `STAGE_ORDER` の全ステージ名をキーに持つ dict（pending/running/done/failed）。
    """
    stages: dict[str, str] = {name: "pending" for name in STAGE_ORDER}
    for event in events:
        stage = str(event.get("stage"))
        if stage in stages:
            stages[stage] = str(event.get("stage_status"))

    if not events:
        return {
            "run_id": run_id,
            "symbol": None,
            "horizon_type": None,
            "status": "pending",
            "started_at": None,
            "finished_at": None,
            "pick_id": None,
            "stages": stages,
        }

    last = events[-1]
    run_status = str(last.get("status"))
    last_stage = last.get("stage")
    if run_status == "running" and last_stage in STAGE_ORDER:
        completed_idx = STAGE_ORDER.index(cast("StageName", last_stage))
        next_idx = completed_idx + 1
        if next_idx < len(STAGE_ORDER):
            stages[STAGE_ORDER[next_idx]] = "running"

    return {
        "run_id": run_id,
        "symbol": last.get("symbol"),
        "horizon_type": last.get("horizon_type"),
        "status": run_status,
        "started_at": last.get("started_at"),
        "finished_at": last.get("finished_at"),
        "pick_id": last.get("pick_id"),
        "stages": stages,
    }
