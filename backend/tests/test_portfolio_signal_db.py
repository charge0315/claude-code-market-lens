"""`portfolio_signal_db`（AI 売買タイミング判定の読み書き）の検証."""

from __future__ import annotations

from pathlib import Path

from backend.services.db.portfolio_signal_db import (
    get_latest_approved_signal,
    get_signal,
    insert_signal,
    list_signals,
    set_fill_report,
    set_status,
    supersede_pending,
)
from backend.services.db.portfolio_signal_shadow_db import get_shadows_for_signals, insert_shadow


async def test_insert_signal_defaults_to_proposed(migrated_db: Path) -> None:
    signal_id = await insert_signal(
        symbol="7203", action="hold", stop=950.0, target=1100.0, confidence=70.0, rationale="堅調"
    )

    row = await get_signal(signal_id)
    assert row is not None
    assert row["status"] == "proposed"
    assert row["entry"] is None
    assert row["action"] == "hold"


async def test_insert_signal_with_entry_for_add_action(migrated_db: Path) -> None:
    signal_id = await insert_signal(
        symbol="7203", action="add", entry=1050.0, stop=1000.0, target=1200.0, confidence=65.0, rationale="押し目"
    )

    row = await get_signal(signal_id)
    assert row is not None
    assert row["entry"] == 1050.0


async def test_get_signal_unknown_returns_none(migrated_db: Path) -> None:
    assert await get_signal("does-not-exist") is None


async def test_list_signals_orders_newest_first(migrated_db: Path) -> None:
    first = await insert_signal(
        symbol="7203",
        action="hold",
        stop=900.0,
        target=1100.0,
        confidence=60.0,
        rationale="x",
        evaluated_at="2026-06-01T09:00:00+09:00",
    )
    second = await insert_signal(
        symbol="6758",
        action="hold",
        stop=900.0,
        target=1100.0,
        confidence=60.0,
        rationale="x",
        evaluated_at="2026-06-01T09:05:00+09:00",
    )

    rows = await list_signals()
    assert [r["signal_id"] for r in rows] == [second, first]


async def test_list_signals_filters_by_status(migrated_db: Path) -> None:
    proposed = await insert_signal(
        symbol="7203", action="hold", stop=900.0, target=1100.0, confidence=60.0, rationale="x"
    )
    approved = await insert_signal(
        symbol="6758", action="trim", stop=900.0, target=1100.0, confidence=60.0, rationale="x"
    )
    await set_status(approved, "approved")

    proposed_rows = await list_signals(status="proposed")
    approved_rows = await list_signals(status="approved")
    assert [r["signal_id"] for r in proposed_rows] == [proposed]
    assert [r["signal_id"] for r in approved_rows] == [approved]


async def test_set_status_updates_and_returns_true(migrated_db: Path) -> None:
    signal_id = await insert_signal(
        symbol="7203", action="hold", stop=900.0, target=1100.0, confidence=60.0, rationale="x"
    )

    ok = await set_status(signal_id, "approved")
    assert ok is True
    row = await get_signal(signal_id)
    assert row is not None and row["status"] == "approved"


async def test_set_status_unknown_returns_false(migrated_db: Path) -> None:
    assert await set_status("does-not-exist", "approved") is False


async def test_set_fill_report_marks_executed(migrated_db: Path) -> None:
    signal_id = await insert_signal(
        symbol="7203", action="trim", stop=900.0, target=1100.0, confidence=60.0, rationale="x"
    )
    await set_status(signal_id, "approved")

    ok = await set_fill_report(signal_id, '{"executed_price": 1050.0}')
    assert ok is True

    row = await get_signal(signal_id)
    assert row is not None
    assert row["status"] == "executed"
    assert row["fill_report"] == '{"executed_price": 1050.0}'


async def test_set_fill_report_unknown_returns_false(migrated_db: Path) -> None:
    assert await set_fill_report("does-not-exist", "{}") is False


async def test_supersede_pending_deletes_only_proposed_for_symbol(migrated_db: Path) -> None:
    stale = await insert_signal(symbol="7203", action="hold", stop=900.0, target=1100.0, confidence=60.0, rationale="x")
    other_symbol = await insert_signal(
        symbol="6758", action="hold", stop=900.0, target=1100.0, confidence=60.0, rationale="x"
    )
    approved_same_symbol = await insert_signal(
        symbol="7203", action="trim", stop=900.0, target=1100.0, confidence=60.0, rationale="x"
    )
    await set_status(approved_same_symbol, "approved")

    deleted = await supersede_pending("7203")

    assert deleted == 1
    assert await get_signal(stale) is None
    assert await get_signal(other_symbol) is not None
    row = await get_signal(approved_same_symbol)
    assert row is not None and row["status"] == "approved"


async def test_supersede_pending_also_removes_shadow_judgments(migrated_db: Path) -> None:
    stale = await insert_signal(symbol="7203", action="hold", stop=900.0, target=1100.0, confidence=60.0, rationale="x")
    await insert_shadow(
        signal_id=stale,
        challenger_version="gemini:test",
        action="hold",
        stop=900.0,
        target=1100.0,
        confidence=55.0,
        reasoning="x",
    )

    await supersede_pending("7203")

    assert await get_shadows_for_signals([stale]) == {}


async def test_supersede_pending_no_rows_returns_zero(migrated_db: Path) -> None:
    assert await supersede_pending("7203") == 0


async def _insert_with_status(symbol: str, stop: float, evaluated_at: str, status: str) -> str:
    signal_id = await insert_signal(
        symbol=symbol,
        action="hold",
        stop=stop,
        target=stop * 2,
        confidence=60.0,
        rationale="x",
        evaluated_at=evaluated_at,
    )
    if status == "executed":
        await set_fill_report(signal_id, "{}")
    elif status != "proposed":
        await set_status(signal_id, status)
    return signal_id


async def test_get_latest_approved_signal_returns_newest_approved_or_executed(migrated_db: Path) -> None:
    await _insert_with_status("3856", 171.25, "2026-09-24T09:30:00+09:00", "approved")
    await _insert_with_status("3856", 175.0, "2026-09-24T10:00:00+09:00", "executed")

    row = await get_latest_approved_signal("3856", since="2026-09-01")
    assert row is not None and row["stop"] == 175.0


async def test_get_latest_approved_signal_ignores_proposed_and_rejected(migrated_db: Path) -> None:
    await _insert_with_status("3856", 171.25, "2026-09-24T09:30:00+09:00", "approved")
    await _insert_with_status("3856", 180.0, "2026-09-24T10:00:00+09:00", "rejected")
    await _insert_with_status("3856", 185.0, "2026-09-24T10:05:00+09:00", "proposed")

    row = await get_latest_approved_signal("3856", since="2026-09-01")
    assert row is not None and row["stop"] == 171.25


async def test_get_latest_approved_signal_ignores_signals_before_acquisition(migrated_db: Path) -> None:
    """同じ銘柄を売却後に買い直した場合、前回ポジションの損切値を引き継がない."""
    await _insert_with_status("3856", 171.25, "2026-09-10T09:30:00+09:00", "approved")

    assert await get_latest_approved_signal("3856", since="2026-09-20") is None


async def test_get_latest_approved_signal_is_per_symbol(migrated_db: Path) -> None:
    await _insert_with_status("7203", 900.0, "2026-09-24T09:30:00+09:00", "approved")

    assert await get_latest_approved_signal("3856", since="2026-09-01") is None
