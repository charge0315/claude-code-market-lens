"""`portfolio_service.build_portfolio` の検証（価格取得はモック）."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from backend.services.db.portfolio_db import insert_holding
from backend.services.portfolio import portfolio_service as svc


def _hist(closes: list[float]) -> pd.DataFrame:
    return pd.DataFrame({"Close": closes})


_FetcherTable = dict[str, tuple[dict[str, str | None] | None, pd.DataFrame]]


@pytest.fixture(autouse=True)
def _stub_fetchers(monkeypatch: pytest.MonkeyPatch) -> _FetcherTable:
    """symbol -> (company_info, hist) を差し替えられるようにする."""
    table: _FetcherTable = {}

    def fake_get_company_info(symbol: str) -> dict[str, str | None] | None:
        return table[symbol][0]

    def fake_fetch_stock_data(symbol: str, period: str, interval: str) -> pd.DataFrame:  # noqa: ARG001
        return table[symbol][1]

    monkeypatch.setattr(svc, "get_company_info", fake_get_company_info)
    monkeypatch.setattr(svc, "fetch_stock_data", fake_fetch_stock_data)
    return table


async def test_build_portfolio_computes_pnl_and_day_change(migrated_db: Path, _stub_fetchers: _FetcherTable) -> None:
    await insert_holding(symbol="7203", quantity=100, avg_cost=1000.0, acquired_at="2026-01-15")
    _stub_fetchers["7203"] = ({"name": "トヨタ", "sector": "輸送用機器"}, _hist([1050.0, 1100.0]))

    summary = await svc.build_portfolio()

    assert summary.holding_count == 1
    h = summary.holdings[0]
    assert h.current_price == 1100.0
    assert h.cost_basis == 100_000.0
    assert h.current_value == 110_000.0
    assert h.gain_loss == 10_000.0
    assert h.return_pct == pytest.approx(0.10)
    assert summary.day_gain_loss == pytest.approx(100 * (1100.0 - 1050.0))
    assert summary.total_gain_loss == 10_000.0


async def test_build_portfolio_groups_by_sector(migrated_db: Path, _stub_fetchers: _FetcherTable) -> None:
    await insert_holding(symbol="7203", quantity=10, avg_cost=1000.0, acquired_at="2026-01-15")
    await insert_holding(symbol="6758", quantity=10, avg_cost=2000.0, acquired_at="2026-01-16")
    _stub_fetchers["7203"] = ({"name": "A", "sector": "輸送用機器"}, _hist([1000.0]))
    _stub_fetchers["6758"] = ({"name": "B", "sector": "電気機器"}, _hist([2000.0]))

    summary = await svc.build_portfolio()

    sectors = {a.sector for a in summary.sector_allocations}
    assert sectors == {"輸送用機器", "電気機器"}
    assert sum(a.pct for a in summary.sector_allocations) == pytest.approx(100.0)


async def test_build_portfolio_unknown_sector_falls_back(migrated_db: Path, _stub_fetchers: _FetcherTable) -> None:
    await insert_holding(symbol="7203", quantity=10, avg_cost=1000.0, acquired_at="2026-01-15")
    _stub_fetchers["7203"] = (None, pd.DataFrame())

    summary = await svc.build_portfolio()

    assert summary.holdings[0].current_price is None
    assert summary.holdings[0].gain_loss is None
    assert summary.sector_allocations[0].sector == "その他"
    # 現在価格が取得できないロットはコスト基準で評価額に計上される。
    assert summary.total_value == 10_000.0


async def test_build_portfolio_day_gain_loss_none_when_no_prev_close(
    migrated_db: Path, _stub_fetchers: _FetcherTable
) -> None:
    await insert_holding(symbol="7203", quantity=10, avg_cost=1000.0, acquired_at="2026-01-15")
    _stub_fetchers["7203"] = ({"name": "A", "sector": "輸送用機器"}, _hist([1000.0]))  # 1本しかない=前日終値なし

    summary = await svc.build_portfolio()

    assert summary.day_gain_loss is None


async def test_build_portfolio_empty(migrated_db: Path) -> None:
    summary = await svc.build_portfolio()
    assert summary.holding_count == 0
    assert summary.holdings == []
    assert summary.total_value == 0.0
    assert summary.total_return_pct == 0.0
