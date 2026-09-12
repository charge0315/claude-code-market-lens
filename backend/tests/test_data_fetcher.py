"""株価データ取得サービスの検証（Market Lens から移植）.

yfinance / J-Quants は叩かず、シンボル解決・CSV 正規化・銘柄検索のフォールバックを確認する。
"""

from __future__ import annotations

import pandas as pd
import pytest

from backend.services.data import data_fetcher as df_mod
from backend.services.data.data_fetcher import (
    MAJOR_JP_STOCKS,
    ensure_ticker_suffix,
    get_company_name,
    parse_csv_data,
    search_tickers,
)


@pytest.fixture(autouse=True)
def _reset_master_cache() -> None:
    df_mod._ticker_master_cache = None


class _UnconfiguredJQuants:
    """`is_configured` が False の J-Quants クライアントスタブ（プロパティは差し替えられないため）."""

    is_configured = False

    async def fetch_all_listed_stocks(self) -> list[dict[str, object]]:
        return []


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("7203", "7203.T"),
        ("7203.T", "7203.T"),
        ("166A", "166A.T"),
        ("25935", "25935.T"),
        ("AAPL", "AAPL"),  # 数字を含まない → 付与しない
        ("  6758  ", "6758.T"),
    ],
)
def test_ensure_ticker_suffix(raw: str, expected: str) -> None:
    assert ensure_ticker_suffix(raw) == expected


def test_parse_csv_data_normalizes_columns() -> None:
    csv = b"date,open,high,low,close,volume\n2026-09-10,100,110,99,108,1000\n"
    df = parse_csv_data(csv)
    assert list(df.columns) == ["Date", "Open", "High", "Low", "Close", "Volume"]
    assert df["Close"].iloc[0] == 108


async def test_search_tickers_falls_back_to_major_stocks_when_jquants_unconfigured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(df_mod, "jquants", _UnconfiguredJQuants())
    results = await search_tickers("トヨタ")
    assert any(t.code == "7203" for t in results)


async def test_search_tickers_empty_query_returns_empty() -> None:
    assert await search_tickers("   ") == []


async def test_search_tickers_matches_by_code(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(df_mod, "jquants", _UnconfiguredJQuants())
    results = await search_tickers("6758")
    assert [t.code for t in results] == ["6758"]
    assert MAJOR_JP_STOCKS["6758"].name == "ソニーグループ"


async def test_get_company_name_resolves_from_ticker_master(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(df_mod, "jquants", _UnconfiguredJQuants())
    assert await get_company_name("7203") == "トヨタ自動車"


async def test_get_company_name_returns_none_for_unknown_code(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(df_mod, "jquants", _UnconfiguredJQuants())
    assert await get_company_name("0000") is None


def test_fetch_stock_data_uses_cache_then_yfinance(monkeypatch: pytest.MonkeyPatch) -> None:
    frame = pd.DataFrame({"Close": [1.0, 2.0]}, index=pd.to_datetime(["2026-09-09", "2026-09-10"]))

    class FakeTicker:
        def __init__(self, _symbol: str) -> None:
            pass

        def history(self, period: str, interval: str) -> pd.DataFrame:  # noqa: ARG002
            return frame

    monkeypatch.setattr(df_mod.yf, "Ticker", FakeTicker)
    monkeypatch.setattr(df_mod.stock_cache, "get_dataframe", lambda _k: None)
    saved: dict[str, pd.DataFrame] = {}
    monkeypatch.setattr(df_mod.stock_cache, "set_dataframe", lambda k, v, ttl: saved.setdefault(k, v))

    out = df_mod.fetch_stock_data("7203", period="1mo", interval="1d")
    assert out.equals(frame)
    assert saved  # キャッシュへ保存された
