"""推論トレース API（`routers/inference.py`）の検証."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

from backend.models.inference import InferenceOutcome
from backend.routers import inference as inference_router
from backend.services.db.shadow_prediction_db import insert_shadow_prediction
from backend.services.inference import orchestrator as orch
from backend.tests.test_pick_pipeline import WiredState, _FakeLLM, _rec


@pytest.fixture
def wired(monkeypatch: pytest.MonkeyPatch) -> WiredState:
    state = WiredState()
    monkeypatch.setattr(orch, "resolve_feature_provider", lambda _feature: _FakeLLM(state))
    # shadow プロバイダ無し（実 API への意図しないアクセスを防ぐ）。
    monkeypatch.setattr(orch, "resolve_shadow_providers", lambda _feature: [])

    async def fake_brand(_code: str) -> None:
        return None

    monkeypatch.setattr(orch, "get_brand_note", fake_brand)

    async def fake_news_sentiment(_code: str) -> None:
        return None

    monkeypatch.setattr(orch, "get_llm_news_sentiment", fake_news_sentiment)
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


async def _wait_until(predicate: object, *, timeout: float = 2.0, interval: float = 0.02) -> None:
    """バックグラウンドタスクの完了をポーリングで待つ（テスト専用の小さなヘルパー）."""
    elapsed = 0.0
    while not predicate() and elapsed < timeout:  # type: ignore[operator]
        await asyncio.sleep(interval)
        elapsed += interval


async def test_trigger_sandbox_returns_run_id_and_runs_in_background(
    migrated_db: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[tuple[str, str, str]] = []

    async def fake_run_sandbox(symbol: str, horizon_type: str, *, run_id: str) -> None:
        calls.append((symbol, horizon_type, run_id))

    monkeypatch.setattr(inference_router, "run_sandbox_inference", fake_run_sandbox)
    monkeypatch.setattr(inference_router, "is_daily_limit_exceeded", lambda: _async_false())

    from backend.main import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        res = await client.post("/api/inference/sandbox", json={"symbol": "7203", "horizon_type": "mid_term"})

    assert res.status_code == 200
    body = res.json()
    assert body["success"] is True
    run_id = body["data"]["run_id"]
    assert run_id

    await _wait_until(lambda: len(calls) == 1)
    assert calls == [("7203", "mid_term", run_id)]


async def _async_false() -> bool:
    return False


async def _async_true() -> bool:
    return True


async def test_trigger_sandbox_rejects_when_daily_cost_limit_exceeded(
    migrated_db: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(inference_router, "is_daily_limit_exceeded", lambda: _async_true())

    from backend.main import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        res = await client.post("/api/inference/sandbox", json={"symbol": "7203", "horizon_type": "mid_term"})

    assert res.status_code == 429


async def test_trigger_sandbox_rejects_duplicate_concurrent_trigger(
    migrated_db: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    release = asyncio.Event()

    async def blocking_run_sandbox(symbol: str, horizon_type: str, *, run_id: str) -> None:  # noqa: ARG001
        await release.wait()

    monkeypatch.setattr(inference_router, "run_sandbox_inference", blocking_run_sandbox)
    monkeypatch.setattr(inference_router, "is_daily_limit_exceeded", lambda: _async_false())

    from backend.main import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        first = await client.post("/api/inference/sandbox", json={"symbol": "7203", "horizon_type": "mid_term"})
        assert first.status_code == 200

        second = await client.post("/api/inference/sandbox", json={"symbol": "7203", "horizon_type": "mid_term"})
        assert second.status_code == 409

    release.set()  # ぶら下がったバックグラウンドタスクを後始末する


async def test_sandbox_shadow_endpoint_returns_recorded_predictions(migrated_db: Path) -> None:
    await insert_shadow_prediction(
        pick_id=None,
        run_id="run-shadow-1",
        challenger_version="gemini:gemini-2.5-pro",
        symbol="7203",
        horizon_type="mid_term",
        direction="bullish",
        entry=1000.0,
        stop=950.0,
        target=1100.0,
        confidence_raw=70.0,
        confidence=70.0,
        payload={"reasoning": "Gemini 側の根拠", "risk_factors": ["需給悪化"], "holding_period_days": 6},
    )

    from backend.main import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        res = await client.get("/api/inference/run-shadow-1/shadow")

    body = res.json()
    assert body["success"] is True
    assert len(body["data"]) == 1
    row = body["data"][0]
    assert row["challenger_version"] == "gemini:gemini-2.5-pro"
    assert row["reasoning"] == "Gemini 側の根拠"
    assert row["risk_factors"] == ["需給悪化"]
    assert row["holding_period_days"] == 6


async def test_sandbox_shadow_endpoint_returns_empty_for_unknown_run(migrated_db: Path) -> None:
    from backend.main import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        res = await client.get("/api/inference/does-not-exist/shadow")

    assert res.json()["data"] == []
