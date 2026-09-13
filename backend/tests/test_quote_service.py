"""`quote_service.fetch_quote`（🆕 P13、現在値/前日終値のライブ取得）の検証."""

from __future__ import annotations

import pandas as pd
import pytest

from backend.services.data import quote_service


def _hist(closes: list[float]) -> pd.DataFrame:
    return pd.DataFrame({"Close": closes})


async def test_returns_current_and_prev_close(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(quote_service, "fetch_stock_data", lambda *_a, **_kw: _hist([1050.0, 1100.0]))
    current, prev = await quote_service.fetch_quote("7203")
    assert current == 1100.0
    assert prev == 1050.0


async def test_single_bar_has_no_prev_close(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(quote_service, "fetch_stock_data", lambda *_a, **_kw: _hist([1100.0]))
    current, prev = await quote_service.fetch_quote("7203")
    assert current == 1100.0
    assert prev is None


async def test_empty_history_returns_none_none(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(quote_service, "fetch_stock_data", lambda *_a, **_kw: pd.DataFrame())
    assert await quote_service.fetch_quote("7203") == (None, None)


async def test_fetch_failure_is_fail_soft(monkeypatch: pytest.MonkeyPatch) -> None:
    def _raise(*_a: object, **_kw: object) -> pd.DataFrame:
        raise RuntimeError("yfinance down")

    monkeypatch.setattr(quote_service, "fetch_stock_data", _raise)
    assert await quote_service.fetch_quote("7203") == (None, None)


async def test_fetch_quote_with_spark_returns_full_series(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(quote_service, "fetch_stock_data", lambda *_a, **_kw: _hist([1000.0, 1050.0, 1100.0]))
    current, prev, spark = await quote_service.fetch_quote_with_spark("7203")
    assert current == 1100.0
    assert prev == 1050.0
    assert spark == [1000.0, 1050.0, 1100.0]


async def test_fetch_quote_with_spark_empty_history_is_fail_soft(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(quote_service, "fetch_stock_data", lambda *_a, **_kw: pd.DataFrame())
    assert await quote_service.fetch_quote_with_spark("7203") == (None, None, [])


async def test_fetch_quote_delegates_to_fetch_quote_with_spark(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(quote_service, "fetch_stock_data", lambda *_a, **_kw: _hist([1050.0, 1100.0, 1150.0]))
    # fetch_quote は spark を捨てて (current, prev) だけ返す薄いラッパであることを確認する。
    assert await quote_service.fetch_quote("7203") == (1150.0, 1100.0)
