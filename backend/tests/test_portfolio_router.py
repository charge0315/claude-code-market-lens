"""ポートフォリオ API（`routers/portfolio.py`）の検証."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest
from httpx import ASGITransport, AsyncClient

from backend.services.portfolio import portfolio_service as psvc


@pytest.fixture(autouse=True)
def _stub_fetchers(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_get_company_info(_symbol: str) -> dict[str, str | None]:
        return {"name": "会社名", "sector": "輸送用機器"}

    def fake_fetch_stock_data(_symbol: str, period: str, interval: str) -> pd.DataFrame:  # noqa: ARG001
        return pd.DataFrame({"Close": [1000.0, 1010.0]})

    monkeypatch.setattr(psvc, "get_company_info", fake_get_company_info)
    monkeypatch.setattr(psvc, "fetch_stock_data", fake_fetch_stock_data)


async def test_portfolio_crud_and_get_flow(migrated_db: Path) -> None:
    from backend.main import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        empty = (await client.get("/api/portfolio")).json()
        assert empty["success"] is True
        assert empty["data"]["holding_count"] == 0

        add_res = await client.post(
            "/api/portfolio/holdings",
            json={"symbol": "7203", "quantity": 100, "avg_cost": 1000.0, "acquired_at": "2026-01-15"},
        )
        assert add_res.status_code == 201
        holding_id = add_res.json()["data"]["holding_id"]

        summary = (await client.get("/api/portfolio")).json()
        assert summary["data"]["holding_count"] == 1
        assert summary["data"]["holdings"][0]["symbol"] == "7203"
        assert summary["data"]["holdings"][0]["current_price"] == 1010.0

        update_res = await client.put(
            f"/api/portfolio/holdings/{holding_id}", json={"quantity": 200, "avg_cost": 1100.0}
        )
        assert update_res.json()["success"] is True

        summary2 = (await client.get("/api/portfolio")).json()
        assert summary2["data"]["holdings"][0]["quantity"] == 200

        delete_res = await client.delete(f"/api/portfolio/holdings/{holding_id}")
        assert delete_res.json()["success"] is True

        summary3 = (await client.get("/api/portfolio")).json()
        assert summary3["data"]["holding_count"] == 0


async def test_add_holding_rejects_non_positive_quantity(migrated_db: Path) -> None:
    from backend.main import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        res = await client.post(
            "/api/portfolio/holdings",
            json={"symbol": "7203", "quantity": 0, "avg_cost": 1000.0, "acquired_at": "2026-01-15"},
        )
    assert res.status_code == 422


async def test_add_duplicate_lot_returns_conflict(migrated_db: Path) -> None:
    from backend.main import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        payload = {"symbol": "7203", "quantity": 100, "avg_cost": 1000.0, "acquired_at": "2026-01-15"}
        first = await client.post("/api/portfolio/holdings", json=payload)
        assert first.status_code == 201

        second = await client.post("/api/portfolio/holdings", json=payload)
    assert second.status_code == 409


async def test_update_unknown_holding_returns_404(migrated_db: Path) -> None:
    from backend.main import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        res = await client.put("/api/portfolio/holdings/does-not-exist", json={"quantity": 1, "avg_cost": 1.0})
    assert res.status_code == 404


async def test_delete_unknown_holding_returns_404(migrated_db: Path) -> None:
    from backend.main import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        res = await client.delete("/api/portfolio/holdings/does-not-exist")
    assert res.status_code == 404


async def test_risk_endpoint_returns_report(migrated_db: Path) -> None:
    from backend.main import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        res = await client.get("/api/portfolio/risk")
    body = res.json()
    assert body["success"] is True
    assert body["data"]["analyzed_count"] == 0
    assert body["data"]["message"] == "保有銘柄がありません"
