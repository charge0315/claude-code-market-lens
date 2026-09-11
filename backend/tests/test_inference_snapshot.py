"""build_snapshot（DAG スナップショット構築の純関数）のテスト."""

from __future__ import annotations

from typing import cast

from backend.models.inference import STAGE_ORDER
from backend.services.inference.snapshot import build_snapshot


def _stages(snap: dict[str, object]) -> dict[str, str]:
    return cast("dict[str, str]", snap["stages"])


def _event(stage: str, stage_status: str, status: str, **extra: object) -> dict[str, object]:
    base: dict[str, object] = {
        "stage": stage,
        "stage_status": stage_status,
        "status": status,
        "symbol": "7203",
        "horizon_type": "mid_term",
        "started_at": "2026-06-01T08:50:00+09:00",
        "finished_at": None,
        "pick_id": None,
    }
    base.update(extra)
    return base


def test_no_events_returns_all_pending() -> None:
    snap = build_snapshot("run-1", [])
    assert snap["status"] == "pending"
    assert snap["stages"] == {name: "pending" for name in STAGE_ORDER}


def test_partial_run_marks_next_stage_as_running() -> None:
    events = [
        _event("collect", "done", "running"),
        _event("subscore", "done", "running"),
    ]
    snap = build_snapshot("run-1", events)
    stages = _stages(snap)
    assert stages["collect"] == "done"
    assert stages["subscore"] == "done"
    assert stages["synthesis"] == "running"  # 次のステージを推定 running とする
    assert stages["llm_overlay"] == "pending"
    assert stages["bracket"] == "pending"
    assert stages["verify"] == "pending"
    assert snap["status"] == "running"


def test_completed_run_has_no_running_stage() -> None:
    events = [_event(name, "done", "running") for name in STAGE_ORDER[:-1]]
    events.append(_event("verify", "done", "done", pick_id="pick-1"))
    snap = build_snapshot("run-1", events)
    assert _stages(snap) == {name: "done" for name in STAGE_ORDER}
    assert snap["status"] == "done"
    assert snap["pick_id"] == "pick-1"


def test_failed_run_stops_marking_running_after_failure() -> None:
    events = [
        _event("collect", "done", "running"),
        _event("subscore", "done", "running"),
        _event("synthesis", "done", "running"),
        _event("llm_overlay", "failed", "rejected"),
    ]
    snap = build_snapshot("run-1", events)
    stages = _stages(snap)
    assert stages["llm_overlay"] == "failed"
    # run が終端（rejected）に達しているので、以降のステージは running 推定を行わない。
    assert stages["bracket"] == "pending"
    assert stages["verify"] == "pending"
    assert snap["status"] == "rejected"


def test_running_at_last_stage_has_no_next_to_mark() -> None:
    events = [_event(name, "done", "running") for name in STAGE_ORDER]
    snap = build_snapshot("run-1", events)
    # verify が最後のステージなので推定 running 対象が無い（実際は最後の行で status が変わるはず
    # だが、純関数としては "running" のまま渡された入力もそのまま扱う）。
    assert _stages(snap)["verify"] == "done"
