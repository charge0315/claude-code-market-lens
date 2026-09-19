"""学習対象設定 API（🆕 /api/registry/training-settings 等）の検証."""

from __future__ import annotations

from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

from backend.models.stocks import TickerInfo
from backend.routers import registry as registry_router
from backend.services.db import training_target_db


def _universe() -> list[TickerInfo]:
    return [
        TickerInfo(code="1111", name="あいう銘柄", sector="サービス業"),
        TickerInfo(code="2222", name="かきく銘柄", sector="化学"),
    ]


async def _universe_awaitable() -> list[TickerInfo]:
    return _universe()


async def test_get_training_settings_returns_defaults_when_unsaved(migrated_db: Path) -> None:
    from backend.main import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        res = await client.get("/api/registry/training-settings")

    body = res.json()
    assert body["success"] is True
    assert body["data"] == {"target_mode": "all", "max_parallel_workers": 4}


async def test_update_training_settings_persists(migrated_db: Path) -> None:
    from backend.main import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        res = await client.put(
            "/api/registry/training-settings", json={"target_mode": "custom", "max_parallel_workers": 8}
        )
        followup = await client.get("/api/registry/training-settings")

    assert res.json()["data"] == {"target_mode": "custom", "max_parallel_workers": 8}
    assert followup.json()["data"] == {"target_mode": "custom", "max_parallel_workers": 8}


async def test_update_training_settings_clamps_out_of_range_workers(migrated_db: Path) -> None:
    from backend.main import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        res = await client.put("/api/registry/training-settings", json={"max_parallel_workers": 999})

    assert res.json()["data"]["max_parallel_workers"] == 16


async def test_training_target_tickers_round_trip_resolves_names(
    migrated_db: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(registry_router, "_get_ticker_master", lambda: _universe_awaitable())

    from backend.main import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        put_res = await client.put("/api/registry/training-target-tickers", json={"codes": ["1111", "2222"]})
        get_res = await client.get("/api/registry/training-target-tickers")

    for body in (put_res.json(), get_res.json()):
        assert body["success"] is True
        codes = {row["code"]: row for row in body["data"]}
        assert codes["1111"]["name"] == "あいう銘柄"
        assert codes["2222"]["sector"] == "化学"


async def test_training_target_tickers_replace_removes_deselected(migrated_db: Path) -> None:
    await training_target_db.add_custom_tickers(["1111", "2222"])

    from backend.main import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        res = await client.put("/api/registry/training-target-tickers", json={"codes": ["1111"]})

    codes = [row["code"] for row in res.json()["data"]]
    assert codes == ["1111"]


async def test_ticker_universe_endpoint_filters_and_sorts(migrated_db: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(registry_router, "list_ticker_universe", _fake_list_ticker_universe)

    from backend.main import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        res = await client.get("/api/registry/ticker-universe?sector=化学&sort=volume_desc&q=かきく")

    body = res.json()
    assert body["success"] is True
    assert [row["code"] for row in body["data"]] == ["2222"]


async def _fake_list_ticker_universe(
    *, sector: str | None = None, sort: str = "code_asc", q: str | None = None
) -> list[dict[str, object]]:
    assert sector == "化学"
    assert sort == "volume_desc"
    assert q == "かきく"
    return [{"code": "2222", "name": "かきく銘柄", "sector": "化学", "volume": 900.0, "in_custom_list": False}]
