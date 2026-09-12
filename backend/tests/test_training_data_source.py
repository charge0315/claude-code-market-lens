"""`training_data_source.fetch_training_ohlcv`（🆕 P14、J-Quants フォールバック）の検証."""

from __future__ import annotations

from collections.abc import Awaitable, Callable

import pandas as pd
import pytest

from backend.services.data.jquants_errors import JQuantsClientError
from backend.services.learning import training_data_source as svc


def _ohlcv(n: int) -> pd.DataFrame:
    return pd.DataFrame({"Close": [float(i) for i in range(n)]})


class _FakeJQuants:
    """`is_configured` がプロパティ（差し替え不可）のため、スタブに差し替えて検証する."""

    def __init__(self, *, configured: bool, fetch: Callable[[str, str], Awaitable[pd.DataFrame]] | None = None) -> None:
        self.is_configured = configured
        self._fetch = fetch

    async def fetch_daily_quotes(self, ticker: str, period: str) -> pd.DataFrame:
        if self._fetch is None:
            raise AssertionError("J-Quants を呼んではいけない状況で呼ばれた")
        return await self._fetch(ticker, period)


async def test_returns_yfinance_data_when_sufficient(monkeypatch: pytest.MonkeyPatch) -> None:
    """yfinance だけで十分な行数があれば J-Quants には触れない（既存挙動の維持）."""
    monkeypatch.setattr(svc, "get_stock_data", lambda ticker, period: _ohlcv(svc.MIN_HISTORY_DAYS))
    monkeypatch.setattr(svc, "jquants", _FakeJQuants(configured=True))

    df = await svc.fetch_training_ohlcv("7203", period="5y")
    assert len(df) == svc.MIN_HISTORY_DAYS


async def test_falls_back_to_jquants_when_yfinance_insufficient(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(svc, "get_stock_data", lambda ticker, period: _ohlcv(10))

    async def _fake_fetch(_ticker: str, _period: str) -> pd.DataFrame:
        return _ohlcv(svc.MIN_HISTORY_DAYS)

    monkeypatch.setattr(svc, "jquants", _FakeJQuants(configured=True, fetch=_fake_fetch))

    df = await svc.fetch_training_ohlcv("166A", period="5y")
    assert len(df) == svc.MIN_HISTORY_DAYS


async def test_falls_back_to_jquants_when_yfinance_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(svc, "get_stock_data", lambda ticker, period: pd.DataFrame())

    async def _fake_fetch(_ticker: str, _period: str) -> pd.DataFrame:
        return _ohlcv(60)

    monkeypatch.setattr(svc, "jquants", _FakeJQuants(configured=True, fetch=_fake_fetch))

    df = await svc.fetch_training_ohlcv("7203", period="5y")
    assert len(df) == 60


async def test_returns_yfinance_result_when_jquants_not_configured(monkeypatch: pytest.MonkeyPatch) -> None:
    """J-Quants 未設定なら yfinance の結果（不足していても）をそのまま返す（フォールバック不要判定）."""
    monkeypatch.setattr(svc, "get_stock_data", lambda ticker, period: _ohlcv(10))
    monkeypatch.setattr(svc, "jquants", _FakeJQuants(configured=False))

    df = await svc.fetch_training_ohlcv("7203", period="5y")
    assert len(df) == 10


async def test_falls_back_to_yfinance_result_when_jquants_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    """J-Quants 側が例外を送出しても学習全体を止めない（フェイルソフト）."""
    monkeypatch.setattr(svc, "get_stock_data", lambda ticker, period: _ohlcv(10))

    async def _raise(_ticker: str, _period: str) -> pd.DataFrame:
        raise JQuantsClientError("/equities/bars/daily", 404)

    monkeypatch.setattr(svc, "jquants", _FakeJQuants(configured=True, fetch=_raise))

    df = await svc.fetch_training_ohlcv("7203", period="5y")
    assert len(df) == 10


async def test_uses_whichever_source_has_more_rows(monkeypatch: pytest.MonkeyPatch) -> None:
    """J-Quants の行数が yfinance を下回る場合は yfinance のままにする."""
    monkeypatch.setattr(svc, "get_stock_data", lambda ticker, period: _ohlcv(30))

    async def _fake_fetch(_ticker: str, _period: str) -> pd.DataFrame:
        return _ohlcv(5)  # yfinance(30) 未満

    monkeypatch.setattr(svc, "jquants", _FakeJQuants(configured=True, fetch=_fake_fetch))

    df = await svc.fetch_training_ohlcv("7203", period="5y")
    assert len(df) == 30
