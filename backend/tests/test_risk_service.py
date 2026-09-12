"""`risk_service.analyze_portfolio_risk` の検証（価格取得はモック）."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from backend.services.data import quote_service
from backend.services.db.portfolio_db import insert_holding
from backend.services.portfolio import portfolio_service as psvc
from backend.services.portfolio import risk_service as svc


def _hist_from_closes(closes: list[float]) -> pd.DataFrame:
    return pd.DataFrame({"Close": closes})


_FetcherTable = dict[str, tuple[dict[str, str | None] | None, pd.DataFrame]]


@pytest.fixture(autouse=True)
def _stub_fetchers(monkeypatch: pytest.MonkeyPatch) -> _FetcherTable:
    """symbol -> (company_info, hist) を portfolio_service / risk_service 双方へ差し替える."""
    table: _FetcherTable = {}

    def fake_get_company_info(symbol: str) -> dict[str, str | None] | None:
        return table[symbol][0]

    def fake_fetch_stock_data(symbol: str, period: str, interval: str) -> pd.DataFrame:  # noqa: ARG001
        return table[symbol][1]

    def fake_get_stock_data(symbol: str, period: str = "1y") -> pd.DataFrame:  # noqa: ARG001
        return table[symbol][1]

    monkeypatch.setattr(psvc, "get_company_info", fake_get_company_info)
    # 🔧 P13: 価格取得は `quote_service.fetch_quote` へ委譲されたため、そちらをパッチする。
    monkeypatch.setattr(quote_service, "fetch_stock_data", fake_fetch_stock_data)
    monkeypatch.setattr(svc.data_fetcher, "get_company_info", fake_get_company_info)
    monkeypatch.setattr(svc.data_fetcher, "get_stock_data", fake_get_stock_data)
    return table


async def test_no_holdings_returns_empty_report_with_message(migrated_db: Path) -> None:
    report = await svc.analyze_portfolio_risk()
    assert report.analyzed_count == 0
    assert report.message == "保有銘柄がありません"
    assert report.correlation_skipped is True


async def test_sector_concentration_flags_above_threshold(migrated_db: Path, _stub_fetchers: _FetcherTable) -> None:
    # 単一銘柄のみ保有 → そのセクターが100%で閾値(40%)超過。
    await insert_holding(symbol="7203", quantity=10, avg_cost=1000.0, acquired_at="2026-01-15")
    _stub_fetchers["7203"] = ({"name": "A", "sector": "輸送用機器"}, _hist_from_closes([1000.0]))

    report = await svc.analyze_portfolio_risk()

    assert len(report.sector_warnings) == 1
    assert report.sector_warnings[0].sector == "輸送用機器"
    assert report.sector_warnings[0].pct == pytest.approx(100.0)
    assert report.sector_warnings[0].exceeds_threshold is True


async def test_correlation_skipped_with_single_holding(migrated_db: Path, _stub_fetchers: _FetcherTable) -> None:
    await insert_holding(symbol="7203", quantity=10, avg_cost=1000.0, acquired_at="2026-01-15")
    _stub_fetchers["7203"] = ({"name": "A", "sector": "輸送用機器"}, _hist_from_closes([1000.0, 1010.0]))

    report = await svc.analyze_portfolio_risk()

    assert report.correlation_skipped is True
    assert report.correlation_warnings == []


async def test_highly_correlated_pair_is_flagged(migrated_db: Path, _stub_fetchers: _FetcherTable) -> None:
    await insert_holding(symbol="7203", quantity=10, avg_cost=1000.0, acquired_at="2026-01-15")
    await insert_holding(symbol="6758", quantity=10, avg_cost=2000.0, acquired_at="2026-01-16")

    rng = np.random.default_rng(0)
    base = 1000.0 * np.cumprod(1.0 + rng.normal(0, 0.01, size=60))
    # ほぼ同じ値動き（相関 ~1.0）にする。
    closes_a = base.tolist()
    closes_b = (base * 2.0 + rng.normal(0, 0.0001, size=60)).tolist()

    _stub_fetchers["7203"] = ({"name": "A", "sector": "輸送用機器"}, _hist_from_closes(closes_a))
    _stub_fetchers["6758"] = ({"name": "B", "sector": "電気機器"}, _hist_from_closes(closes_b))

    report = await svc.analyze_portfolio_risk()

    assert report.correlation_skipped is False
    assert len(report.correlation_warnings) == 1
    warning = report.correlation_warnings[0]
    assert {warning.symbol_a, warning.symbol_b} == {"7203", "6758"}
    assert warning.correlation > 0.7


async def test_uncorrelated_pair_is_not_flagged(migrated_db: Path, _stub_fetchers: _FetcherTable) -> None:
    await insert_holding(symbol="7203", quantity=10, avg_cost=1000.0, acquired_at="2026-01-15")
    await insert_holding(symbol="6758", quantity=10, avg_cost=2000.0, acquired_at="2026-01-16")

    rng = np.random.default_rng(1)
    closes_a = (1000.0 * np.cumprod(1.0 + rng.normal(0, 0.01, size=60))).tolist()
    closes_b = (2000.0 * np.cumprod(1.0 + rng.normal(0, 0.01, size=60))).tolist()

    _stub_fetchers["7203"] = ({"name": "A", "sector": "輸送用機器"}, _hist_from_closes(closes_a))
    _stub_fetchers["6758"] = ({"name": "B", "sector": "電気機器"}, _hist_from_closes(closes_b))

    report = await svc.analyze_portfolio_risk()

    assert report.correlation_skipped is False
    assert report.correlation_warnings == []


async def test_fetch_sector_returns_none_on_failure(migrated_db: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(_symbol: str) -> None:
        raise RuntimeError("network error")

    monkeypatch.setattr(svc.data_fetcher, "get_company_info", boom)

    assert await svc.fetch_sector("7203") is None
