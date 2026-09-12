"""市況スナップショット API（`routers/market.py`、🆕 P13）の検証."""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from backend.models.market import IndexQuote
from backend.routers import market as market_router_module


async def test_get_snapshot_returns_indices_and_status(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_snapshot() -> list[IndexQuote]:
        return [IndexQuote(label="日経平均株価", value=42_300.0, change=300.0, change_pct=0.71)]

    monkeypatch.setattr(market_router_module, "get_market_snapshot", fake_snapshot)
    monkeypatch.setattr(market_router_module, "market_status_label", lambda: "ザラ場中")

    from backend.main import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        res = await client.get("/api/market/snapshot")

    body = res.json()
    assert body["success"] is True
    assert body["data"]["market_status"] == "ザラ場中"
    assert body["data"]["indices"] == [
        {"label": "日経平均株価", "value": 42_300.0, "change": 300.0, "change_pct": 0.71}
    ]
    assert "updated_at" in body["data"]


async def test_get_snapshot_returns_empty_indices_when_all_fail(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_snapshot() -> list[IndexQuote]:
        return []

    monkeypatch.setattr(market_router_module, "get_market_snapshot", fake_snapshot)

    from backend.main import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        res = await client.get("/api/market/snapshot")

    body = res.json()
    assert body["success"] is True
    assert body["data"]["indices"] == []
