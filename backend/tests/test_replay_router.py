"""過去日リプレイ API（🆕 P37）の検証（子プロセス起動はモック）."""

from __future__ import annotations

import datetime
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

from backend.services.db import replay_db
from backend.services.jst_time import JST
from backend.services.replay import runs


@pytest.fixture
def spawned(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    calls: list[str] = []

    def fake_spawn(run_id: str) -> int:
        calls.append(run_id)
        return 4242

    monkeypatch.setattr(runs, "spawn", fake_spawn)
    return calls


async def _client() -> AsyncClient:
    from backend.main import app

    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def test_start_run_with_explicit_dates(migrated_db: Path, spawned: list[str]) -> None:
    async with await _client() as client:
        res = await client.post("/api/replay/runs", json={"start_date": "2025-06-02", "end_date": "2025-09-01"})

    body = res.json()
    assert res.status_code == 200 and body["success"] is True
    run_id = body["data"]["run_id"]
    assert spawned == [run_id]
    run = await replay_db.get_run(run_id)
    assert run is not None
    assert (run["start_date"], run["end_date"], run["pid"]) == ("2025-06-02", "2025-09-01", 4242)


async def test_start_run_defaults_to_four_years(migrated_db: Path, spawned: list[str]) -> None:
    async with await _client() as client:
        res = await client.post("/api/replay/runs", json={})

    run = await replay_db.get_run(res.json()["data"]["run_id"])
    assert run is not None
    start = datetime.date.fromisoformat(str(run["start_date"]))
    end = datetime.date.fromisoformat(str(run["end_date"]))
    assert 4 * 365 - 2 <= (end - start).days <= 4 * 366


@pytest.mark.parametrize(
    "payload",
    [
        {"start_date": "2025-09-01", "end_date": "2025-06-02"},  # 逆順
        {"start_date": "2025-06-02", "end_date": "2999-01-01"},  # 未来
        {"start_date": "2010-01-04", "end_date": "2025-06-02"},  # J-Quants の範囲外すぎ
    ],
)
async def test_start_run_rejects_invalid_ranges(migrated_db: Path, spawned: list[str], payload: dict[str, str]) -> None:
    async with await _client() as client:
        res = await client.post("/api/replay/runs", json=payload)

    assert res.json()["success"] is False
    assert spawned == []


async def test_only_one_alive_run_at_a_time(migrated_db: Path, spawned: list[str]) -> None:
    async with await _client() as client:
        await client.post("/api/replay/runs", json={"start_date": "2025-06-02", "end_date": "2025-09-01"})
        res = await client.post("/api/replay/runs", json={"start_date": "2025-06-02", "end_date": "2025-09-01"})

    assert res.json()["success"] is False
    assert len(spawned) == 1


async def test_stop_and_resume(migrated_db: Path, spawned: list[str]) -> None:
    async with await _client() as client:
        run_id = (
            await client.post("/api/replay/runs", json={"start_date": "2025-06-02", "end_date": "2025-09-01"})
        ).json()["data"]["run_id"]
        await replay_db.update_run(run_id, status="running")

        stop = await client.post(f"/api/replay/runs/{run_id}/stop")
        assert stop.json()["success"] is True
        assert (await replay_db.get_run(run_id) or {})["status"] == "stopping"

        # まだ生きている（ハートビートが新しい）間は再開できない
        assert (await client.post(f"/api/replay/runs/{run_id}/resume")).json()["success"] is False

        await replay_db.update_run(run_id, status="stopped")
        resumed = await client.post(f"/api/replay/runs/{run_id}/resume")

    assert resumed.json()["success"] is True
    assert spawned == [run_id, run_id]


async def test_stale_running_run_can_be_resumed(migrated_db: Path, spawned: list[str]) -> None:
    await replay_db.create_run(
        "00000000-0000-0000-0000-000000000001", start_date="2025-06-02", end_date="2025-09-01", config={}
    )
    old = (datetime.datetime.now(JST) - datetime.timedelta(hours=1)).isoformat(timespec="seconds")
    await replay_db.update_run("00000000-0000-0000-0000-000000000001", status="running", heartbeat_at=old)

    async with await _client() as client:
        res = await client.post("/api/replay/runs/00000000-0000-0000-0000-000000000001/resume")

    assert res.json()["success"] is True


async def test_get_run_detail_and_list(migrated_db: Path, spawned: list[str]) -> None:
    async with await _client() as client:
        run_id = (
            await client.post("/api/replay/runs", json={"start_date": "2025-06-02", "end_date": "2025-09-01"})
        ).json()["data"]["run_id"]
        await replay_db.insert_retrain(run_id, trained_on="2025-06-30", model_version="v", metrics={"auc": 0.56})
        detail = (await client.get(f"/api/replay/runs/{run_id}")).json()
        listing = (await client.get("/api/replay/runs")).json()
        missing = await client.get("/api/replay/runs/00000000-0000-0000-0000-00000000dead")

    data = detail["data"]
    assert data["run"]["run_id"] == run_id
    assert data["run"]["is_alive"] is True
    assert data["pick_counts"] == {}
    assert data["retrains"][0]["metrics"]["auc"] == 0.56
    assert "short_term" in data["live"]
    assert [r["run_id"] for r in listing["data"]] == [run_id]
    assert missing.json()["success"] is False


async def test_invalid_run_id_is_rejected(migrated_db: Path, spawned: list[str]) -> None:
    async with await _client() as client:
        res = await client.post("/api/replay/runs/------------------------------------/resume")

    assert res.status_code == 422
