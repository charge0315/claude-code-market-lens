"""レジストリ API（P5 時点は PSI ドリフトのみ）の検証."""

from __future__ import annotations

from pathlib import Path

from httpx import ASGITransport, AsyncClient

from backend.services.db import drift_db


async def test_drift_endpoint_returns_history(migrated_db: Path) -> None:
    await drift_db.insert_drift_snapshot(
        feature_name="score_breakdown.technical",
        psi=0.31,
        baseline_window="2026-06-01~2026-07-01",
        current_window="2026-08-01~2026-09-01",
        drift_flag=True,
    )

    from backend.main import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        res = await client.get("/api/registry/drift?feature=score_breakdown.technical")
    body = res.json()
    assert body["success"] is True
    assert len(body["data"]) == 1
    assert body["data"][0]["drift_flag"] == 1
    assert body["data"][0]["psi"] == 0.31
