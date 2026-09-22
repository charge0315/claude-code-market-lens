"""株価 OHLC API（`routers/stock.py`）の検証."""

from __future__ import annotations

import pandas as pd
import pytest
from httpx import ASGITransport, AsyncClient

from backend.routers import stock as stock_router_module


def _fake_df() -> pd.DataFrame:
    # 期間切り詰め（`_PERIOD_CALENDAR_DAYS`）の cutoff が「実行時点」基準のため、
    # 固定の過去日付だと将来テスト実行時に cutoff より前になり bars が空になりうる。
    # 直近2営業日相当の動的な日付にして、どの period でも確実に cutoff 以降に収まるようにする。
    index = pd.date_range(end=pd.Timestamp.now().normalize(), periods=2, freq="D")
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


async def test_get_quote_returns_price_and_change_pct(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_fetch_quote(symbol: str) -> tuple[float | None, float | None]:
        assert symbol == "7203"
        return 3025.0, 3000.0

    monkeypatch.setattr(stock_router_module, "fetch_quote", fake_fetch_quote)

    from backend.main import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        res = await client.get("/api/stock/7203/quote")

    body = res.json()
    assert body["success"] is True
    assert body["data"]["symbol"] == "7203"
    assert body["data"]["price"] == 3025.0
    assert body["data"]["prev_close"] == 3000.0
    assert body["data"]["change_pct"] == pytest.approx((3025.0 - 3000.0) / 3000.0 * 100)


async def test_get_quote_returns_null_fields_when_fetch_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_fetch_quote(_symbol: str) -> tuple[float | None, float | None]:
        return None, None

    monkeypatch.setattr(stock_router_module, "fetch_quote", fake_fetch_quote)

    from backend.main import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        res = await client.get("/api/stock/9999/quote")

    body = res.json()
    assert body["success"] is True
    assert body["data"] == {"symbol": "9999", "price": None, "prev_close": None, "change_pct": None}


async def test_get_ohlc_returns_bars(monkeypatch: pytest.MonkeyPatch) -> None:
    df = _fake_df()

    def fake_fetch(_symbol: str, _period: str, _interval: str) -> pd.DataFrame:
        return df

    monkeypatch.setattr(stock_router_module, "fetch_stock_data", fake_fetch)

    from backend.main import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        res = await client.get("/api/stock/7203/ohlc")

    body = res.json()
    assert body["success"] is True
    assert len(body["data"]["bars"]) == 2
    assert body["data"]["bars"][0] == {
        "time": df.index[0].strftime("%Y-%m-%d"),
        "open": 1000.0,
        "high": 1020.0,
        "low": 990.0,
        "close": 1010.0,
        "volume": 1_000_000.0,
    }
    # 2本だけでは SMA25 が計算できないため、兆候イベントは検出されない。
    assert body["data"]["events"] == []


async def test_get_ohlc_passes_extended_period_for_indicator_lookback(monkeypatch: pytest.MonkeyPatch) -> None:
    """SMA25 等の計算精度のため、表示期間より長い期間（`_EXTENDED_PERIOD_FOR`）を要求する."""
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

    assert seen == {"symbol": "6758", "period": "2y", "interval": "1d"}


async def test_get_ohlc_includes_detected_events_within_display_period(monkeypatch: pytest.MonkeyPatch) -> None:
    """`detect_cross_events` が返したイベントのうち、表示期間（cutoff）内のものだけが返る."""
    df = _fake_df()
    monkeypatch.setattr(stock_router_module, "fetch_stock_data", lambda *_a: df)

    in_range_date = df.index[-1].strftime("%Y-%m-%d")
    out_of_range_date = "2000-01-01"
    monkeypatch.setattr(
        stock_router_module,
        "detect_cross_events",
        lambda _df: [
            {"date": in_range_date, "kind": "golden_cross", "label": "GC"},
            {"date": out_of_range_date, "kind": "dead_cross", "label": "DC"},
        ],
    )

    from backend.main import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        res = await client.get("/api/stock/7203/ohlc")

    events = res.json()["data"]["events"]
    assert events == [{"date": in_range_date, "kind": "golden_cross", "label": "GC"}]


async def test_get_ohlc_returns_empty_when_no_data(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_fetch(_symbol: str, _period: str, _interval: str) -> pd.DataFrame:
        return pd.DataFrame()

    monkeypatch.setattr(stock_router_module, "fetch_stock_data", fake_fetch)

    from backend.main import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        res = await client.get("/api/stock/9999/ohlc")

    assert res.json()["data"] == {"bars": [], "events": []}


async def test_get_ohlc_rejects_invalid_period(monkeypatch: pytest.MonkeyPatch) -> None:
    from backend.main import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        res = await client.get("/api/stock/7203/ohlc?period=5min")

    assert res.status_code == 422


async def test_get_ohlc_rejects_invalid_interval(monkeypatch: pytest.MonkeyPatch) -> None:
    from backend.main import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        res = await client.get("/api/stock/7203/ohlc?interval=5m")

    assert res.status_code == 422


def _fake_intraday_df() -> pd.DataFrame:
    """JST タイムゾーン付きの分足 OHLCV（`to_jst().timestamp()` の検証用）."""
    index = pd.date_range(end=pd.Timestamp.now(tz="Asia/Tokyo").normalize(), periods=2, freq="h", tz="Asia/Tokyo")
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


async def test_get_ohlc_intraday_returns_epoch_time_bars_without_events(monkeypatch: pytest.MonkeyPatch) -> None:
    """分足は time が Unix 秒（int）で返り、events は常に空（日付キー衝突を避けるため検出しない）."""
    df = _fake_intraday_df()
    seen: dict[str, object] = {}

    def fake_fetch(symbol: str, period: str, interval: str) -> pd.DataFrame:
        seen["symbol"] = symbol
        seen["period"] = period
        seen["interval"] = interval
        return df

    monkeypatch.setattr(stock_router_module, "fetch_stock_data", fake_fetch)

    from backend.main import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        res = await client.get("/api/stock/7203/ohlc?period=1mo&interval=60m")

    body = res.json()["data"]
    assert seen == {"symbol": "7203", "period": "1mo", "interval": "60m"}
    assert body["events"] == []
    assert len(body["bars"]) == 2
    assert body["bars"][0]["time"] == int(df.index[0].timestamp())
    assert isinstance(body["bars"][0]["time"], int)


async def test_get_ohlc_intraday_clamps_unsupported_period(monkeypatch: pytest.MonkeyPatch) -> None:
    """15分足は Yahoo Finance の分足上限（60日）を超えないよう、対応外の period を丸める."""
    seen: dict[str, object] = {}

    def fake_fetch(symbol: str, period: str, interval: str) -> pd.DataFrame:
        seen["period"] = period
        return _fake_intraday_df()

    monkeypatch.setattr(stock_router_module, "fetch_stock_data", fake_fetch)

    from backend.main import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        await client.get("/api/stock/7203/ohlc?period=6mo&interval=15m")

    assert seen == {"period": "1mo"}


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


async def test_search_returns_matching_tickers(monkeypatch: pytest.MonkeyPatch) -> None:
    from backend.models.stocks import TickerInfo

    async def fake_search_tickers(query: str) -> list[TickerInfo]:
        assert query == "トヨタ"
        return [TickerInfo(code="7203", name="トヨタ自動車", sector="輸送用機器")]

    monkeypatch.setattr(stock_router_module, "search_tickers", fake_search_tickers)

    from backend.main import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        res = await client.get("/api/stock/search?q=トヨタ")

    body = res.json()
    assert body["success"] is True
    assert body["data"] == [{"code": "7203", "name": "トヨタ自動車", "sector": "輸送用機器"}]


async def test_search_without_query_returns_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    from backend.models.stocks import TickerInfo

    async def fake_search_tickers(query: str) -> list[TickerInfo]:
        assert query == ""
        return []

    monkeypatch.setattr(stock_router_module, "search_tickers", fake_search_tickers)

    from backend.main import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        res = await client.get("/api/stock/search")

    assert res.json()["data"] == []
