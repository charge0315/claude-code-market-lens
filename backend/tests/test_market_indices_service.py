"""`market_indices_service.get_market_snapshot`（🆕 P13）の検証."""

from __future__ import annotations

import pandas as pd
import pytest

from backend.services.data import market_indices_service as svc


def _hist(closes: list[float]) -> pd.DataFrame:
    return pd.DataFrame({"Close": closes})


async def test_returns_quote_for_each_resolvable_index(monkeypatch: pytest.MonkeyPatch) -> None:
    table = {
        "^N225": _hist([42_000.0, 42_300.0]),
        "^TPX": _hist([2_970.0, 2_985.0]),
        "^GSPC": pd.DataFrame(),  # 取得失敗（空データ）
        "JPY=X": _hist([150.0, 151.5]),
        "^VIX": _hist([22.0, 21.0]),
    }

    def fake_fetch(symbol: str, _period: str, _interval: str) -> pd.DataFrame:
        return table[symbol]

    monkeypatch.setattr(svc, "fetch_macro_symbol_data", fake_fetch)

    result = await svc.get_market_snapshot()
    labels = {r.label for r in result}
    assert labels == {"日経平均株価", "TOPIX", "USD/JPY", "日経VI"}
    assert "S&P 500" not in labels  # 取得失敗した指数はフェイルソフトで除外

    n225 = next(r for r in result if r.label == "日経平均株価")
    assert n225.value == 42_300.0
    assert n225.change == pytest.approx(300.0)
    assert n225.change_pct == pytest.approx(300.0 / 42_000.0 * 100.0)


async def test_single_bar_index_is_excluded(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(svc, "fetch_macro_symbol_data", lambda *_a, **_kw: _hist([100.0]))
    assert await svc.get_market_snapshot() == []


async def test_fetch_exception_is_fail_soft(monkeypatch: pytest.MonkeyPatch) -> None:
    def _raise(*_a: object, **_kw: object) -> pd.DataFrame:
        raise RuntimeError("yfinance down")

    monkeypatch.setattr(svc, "fetch_macro_symbol_data", _raise)
    assert await svc.get_market_snapshot() == []
