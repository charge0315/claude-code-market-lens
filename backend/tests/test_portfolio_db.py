"""`portfolio_db`（保有銘柄の読み書き）の検証."""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy.exc import IntegrityError

from backend.services.db.portfolio_db import delete_holding, get_holding, insert_holding, list_holdings, update_holding


async def test_insert_and_get_holding(migrated_db: Path) -> None:
    holding_id = await insert_holding(symbol="7203", quantity=100, avg_cost=1000.0, acquired_at="2026-01-15")

    row = await get_holding(holding_id)
    assert row is not None
    assert row["symbol"] == "7203"
    assert row["quantity"] == 100
    assert row["avg_cost"] == 1000.0
    assert row["acquired_at"] == "2026-01-15"
    assert row["created_at"] == row["updated_at"]


async def test_get_holding_unknown_returns_none(migrated_db: Path) -> None:
    assert await get_holding("does-not-exist") is None


async def test_list_holdings_orders_by_acquired_at(migrated_db: Path) -> None:
    await insert_holding(symbol="6758", quantity=10, avg_cost=2000.0, acquired_at="2026-03-01")
    await insert_holding(symbol="7203", quantity=100, avg_cost=1000.0, acquired_at="2026-01-15")

    rows = await list_holdings()
    assert [r["symbol"] for r in rows] == ["7203", "6758"]


async def test_duplicate_symbol_and_acquired_at_raises(migrated_db: Path) -> None:
    await insert_holding(symbol="7203", quantity=100, avg_cost=1000.0, acquired_at="2026-01-15")
    with pytest.raises(IntegrityError):
        await insert_holding(symbol="7203", quantity=50, avg_cost=1100.0, acquired_at="2026-01-15")


async def test_same_symbol_different_lot_is_allowed(migrated_db: Path) -> None:
    await insert_holding(symbol="7203", quantity=100, avg_cost=1000.0, acquired_at="2026-01-15")
    second_id = await insert_holding(symbol="7203", quantity=50, avg_cost=1100.0, acquired_at="2026-02-01")

    rows = await list_holdings()
    assert len(rows) == 2
    assert await get_holding(second_id) is not None


async def test_update_holding_changes_quantity_and_cost(migrated_db: Path) -> None:
    holding_id = await insert_holding(symbol="7203", quantity=100, avg_cost=1000.0, acquired_at="2026-01-15")

    ok = await update_holding(holding_id, quantity=150, avg_cost=1050.0)
    assert ok is True

    row = await get_holding(holding_id)
    assert row is not None
    assert row["quantity"] == 150
    assert row["avg_cost"] == 1050.0


async def test_update_holding_unknown_returns_false(migrated_db: Path) -> None:
    assert await update_holding("does-not-exist", quantity=1, avg_cost=1.0) is False


async def test_delete_holding_removes_row(migrated_db: Path) -> None:
    holding_id = await insert_holding(symbol="7203", quantity=100, avg_cost=1000.0, acquired_at="2026-01-15")

    ok = await delete_holding(holding_id)
    assert ok is True
    assert await get_holding(holding_id) is None


async def test_delete_holding_unknown_returns_false(migrated_db: Path) -> None:
    assert await delete_holding("does-not-exist") is False
