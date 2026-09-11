"""推論トレース API（`routers/inference.py`）の検証."""

from __future__ import annotations

from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

from backend.models.inference import InferenceOutcome
from backend.services.inference import orchestrator as orch
from backend.tests.test_pick_pipeline import WiredState, _FakeLLM, _rec


@pytest.fixture
def wired(monkeypatch: pytest.MonkeyPatch) -> WiredState:
    state = WiredState()
    monkeypatch.setattr(orch, "anthropic_client", _FakeLLM(state))

    async def fake_brand(_code: str) -> None:
        return None

    monkeypatch.setattr(orch, "get_brand_note", fake_brand)
    return state


async def _run_once(state: WiredState) -> InferenceOutcome:
    return await orch.run_inference(
        symbol="7203",
        horizon_type="mid_term",
        batch_run_id="batch-1",
        issued_at="2026-06-01T08:50:00+09:00",
        model_version="test-model",
        rec=_rec("7203"),
        atr=20.0,
        trend_score=55.0,
        news_block=None,
        trend_block=None,
        gate_horizon=20,
    )


async def test_runs_and_snapshot_and_replay_endpoints(wired: WiredState, migrated_db: Path) -> None:
    outcome = await _run_once(wired)

    from backend.main import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        runs_res = (await client.get("/api/inference/runs?horizon_type=mid_term")).json()
        assert runs_res["success"]
        run_ids = {r["run_id"] for r in runs_res["data"]}
        assert outcome.run_id in run_ids

        snap_res = (await client.get(f"/api/inference/{outcome.run_id}")).json()
        assert snap_res["success"]
        data = snap_res["data"]
        assert data["run_id"] == outcome.run_id
        assert data["status"] == "done"
        assert all(v == "done" for v in data["stages"].values())
        assert outcome.pick is not None
        assert data["pick_id"] == outcome.pick.pick_id

        replay_res = (await client.get(f"/api/inference/{outcome.run_id}/replay")).json()
        assert replay_res["success"]
        assert len(replay_res["data"]) == 6
        assert [e["stage"] for e in replay_res["data"]] == [
            "collect",
            "subscore",
            "synthesis",
            "llm_overlay",
            "bracket",
            "verify",
        ]


async def test_snapshot_of_unknown_run_is_all_pending(migrated_db: Path) -> None:
    from backend.main import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        res = (await client.get("/api/inference/does-not-exist")).json()
    assert res["success"]
    assert res["data"]["status"] == "pending"
    assert all(v == "pending" for v in res["data"]["stages"].values())


async def test_stream_endpoint_replays_stored_events_and_terminates(wired: WiredState, migrated_db: Path) -> None:
    outcome = await _run_once(wired)

    from backend.main import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        async with client.stream("GET", f"/api/inference/{outcome.run_id}/stream") as response:
            assert response.status_code == 200
            assert response.headers["content-type"].startswith("text/event-stream")
            body = ""
            async for chunk in response.aiter_text():
                body += chunk
                if "event: done" in body:
                    break

    assert body.count('"stage":') == 6
    assert "event: done" in body
