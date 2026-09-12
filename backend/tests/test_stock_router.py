"""株価 OHLC API（`routers/stock.py`）の検証."""

from __future__ import annotations

import pandas as pd
import pytest
from httpx import ASGITransport, AsyncClient

from backend.routers import stock as stock_router_module


def _fake_df() -> pd.DataFrame:
    index = pd.to_datetime(["2026-06-01", "2026-06-02"])
    return pd.DataFrame(
        {
            "Open": [1000.0, 1010.0],
            "High": [1020.0, 1030.0],
            "Low": [990.0, 1000.0],
            "Close": [1010.0, 1025.0],
            "Volume": [1_000_000.0, 1_200_000.0],
        },
        index=index,
    )


async def test_get_ohlc_returns_bars(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_fetch(_symbol: str, _period: str, _interval: str) -> pd.DataFrame:
        return _fake_df()

    monkeypatch.setattr(stock_router_module, "fetch_stock_data", fake_fetch)

    from backend.main import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        res = await client.get("/api/stock/7203/ohlc")

    body = res.json()
    assert body["success"] is True
    assert len(body["data"]) == 2
    assert body["data"][0] == {
        "time": "2026-06-01",
        "open": 1000.0,
        "high": 1020.0,
        "low": 990.0,
        "close": 1010.0,
        "volume": 1_000_000.0,
    }


async def test_get_ohlc_passes_period_query(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, object] = {}

    def fake_fetch(symbol: str, period: str, interval: str) -> pd.DataFrame:
        seen["symbol"] = symbol
        seen["period"] = period
        seen["interval"] = interval
        return _fake_df()

    monkeypatch.setattr(stock_router_module, "fetch_stock_data", fake_fetch)

    from backend.main import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        await client.get("/api/stock/6758/ohlc?period=1y")

    assert seen == {"symbol": "6758", "period": "1y", "interval": "1d"}


async def test_get_ohlc_returns_empty_list_when_no_data(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_fetch(_symbol: str, _period: str, _interval: str) -> pd.DataFrame:
        return pd.DataFrame()

    monkeypatch.setattr(stock_router_module, "fetch_stock_data", fake_fetch)

    from backend.main import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        res = await client.get("/api/stock/9999/ohlc")

    assert res.json()["data"] == []


async def test_get_ohlc_rejects_invalid_period(monkeypatch: pytest.MonkeyPatch) -> None:
    from backend.main import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        res = await client.get("/api/stock/7203/ohlc?period=5min")

    assert res.status_code == 422


async def test_get_note_returns_content_when_note_exists(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_get_raw_note_content(code: str) -> tuple[str, str] | None:
        assert code == "7203"
        return "7203_トヨタ自動車", "本文テキスト"

    monkeypatch.setattr(stock_router_module, "get_raw_note_content", fake_get_raw_note_content)

    from backend.main import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        res = await client.get("/api/stock/7203/note")

    body = res.json()
    assert body["success"] is True
    assert body["data"] == {"code": "7203", "note_title": "7203_トヨタ自動車", "content": "本文テキスト"}


async def test_get_note_returns_null_data_when_note_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_get_raw_note_content(_code: str) -> None:
        return None

    monkeypatch.setattr(stock_router_module, "get_raw_note_content", fake_get_raw_note_content)

    from backend.main import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        res = await client.get("/api/stock/9999/note")

    body = res.json()
    assert body["success"] is True
    assert body["data"] is None
