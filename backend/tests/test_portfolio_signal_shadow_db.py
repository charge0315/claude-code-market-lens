"""`portfolio_signal_shadow_db`（AI 売買タイミング判定の Gemini 併記）の読み書きの検証."""

from __future__ import annotations

from pathlib import Path

from backend.services.db.portfolio_signal_db import insert_signal
from backend.services.db.portfolio_signal_shadow_db import get_shadows_for_signals, insert_shadow


async def test_get_shadows_for_signals_empty_input_returns_empty_dict(migrated_db: Path) -> None:
    assert await get_shadows_for_signals([]) == {}


async def test_get_shadows_for_signals_without_shadow_omits_key(migrated_db: Path) -> None:
    signal_id = await insert_signal(
        symbol="7203", action="hold", stop=900.0, target=1100.0, confidence=60.0, rationale="x"
    )

    assert await get_shadows_for_signals([signal_id]) == {}


async def test_insert_shadow_and_fetch_by_signal_id(migrated_db: Path) -> None:
    signal_id = await insert_signal(
        symbol="7203", action="hold", stop=900.0, target=1100.0, confidence=60.0, rationale="x"
    )

    shadow_id = await insert_shadow(
        signal_id=signal_id,
        challenger_version="gemini:test",
        action="hold",
        stop=910.0,
        target=1080.0,
        confidence=55.0,
        reasoning="Gemini側の根拠",
    )

    shadows = await get_shadows_for_signals([signal_id])
    assert signal_id in shadows
    row = shadows[signal_id]
    assert row["shadow_id"] == shadow_id
    assert row["action"] == "hold"
    assert row["entry"] is None
    assert row["reasoning"] == "Gemini側の根拠"


async def test_insert_shadow_with_entry_for_add_action(migrated_db: Path) -> None:
    signal_id = await insert_signal(
        symbol="7203", action="add", entry=1050.0, stop=1000.0, target=1200.0, confidence=65.0, rationale="押し目"
    )

    await insert_shadow(
        signal_id=signal_id,
        challenger_version="gemini:test",
        action="add",
        entry=1045.0,
        stop=990.0,
        target=1190.0,
        confidence=60.0,
        reasoning="Gemini側も買い増し判定",
    )

    shadows = await get_shadows_for_signals([signal_id])
    assert shadows[signal_id]["entry"] == 1045.0


async def test_get_shadows_for_signals_batches_multiple_ids(migrated_db: Path) -> None:
    first = await insert_signal(symbol="7203", action="hold", stop=900.0, target=1100.0, confidence=60.0, rationale="x")
    second = await insert_signal(
        symbol="6758", action="hold", stop=900.0, target=1100.0, confidence=60.0, rationale="x"
    )
    await insert_shadow(
        signal_id=first,
        challenger_version="gemini:test",
        action="hold",
        stop=910.0,
        target=1080.0,
        confidence=55.0,
        reasoning="1件目",
    )
    await insert_shadow(
        signal_id=second,
        challenger_version="gemini:test",
        action="trim",
        stop=920.0,
        target=1070.0,
        confidence=50.0,
        reasoning="2件目",
    )

    shadows = await get_shadows_for_signals([first, second])
    assert set(shadows.keys()) == {first, second}
    assert shadows[first]["reasoning"] == "1件目"
    assert shadows[second]["reasoning"] == "2件目"
