"""`services/picks/shadow_picks.list_shadow_picks` の検証."""

from __future__ import annotations

from pathlib import Path

import pytest

from backend.models.pick import LedgerEntry, SubScores
from backend.services.db.shadow_prediction_db import insert_shadow_prediction
from backend.services.ledger import prediction_ledger as pl
from backend.services.picks import shadow_picks as sp


async def _seed_pick(pick_id: str, symbol: str) -> None:
    await pl.insert_pick(
        LedgerEntry(
            pick_id=pick_id,
            run_id="r1",
            issued_at="2026-09-13T08:30:00+09:00",
            horizon_type="mid_term",
            symbol=symbol,
            direction="bullish",
            entry=1000.0,
            stop=950.0,
            target=1100.0,
            sub_scores=SubScores(technical=60, trend=55, fundamental=52, sentiment=50),
            composite_score=60.0,
            concordance=0.6,
            confidence_raw=70.0,
            confidence=70.0,
            confidence_bucket=pl.confidence_bucket(70.0),
            feature_snapshot={},
            rationale_struct={},
            rationale_text="x",
            model_version="v1",
            source_contributions={},
            created_at="2026-09-13T08:30:01+09:00",
        )
    )


@pytest.fixture(autouse=True)
def _no_live_quotes(monkeypatch: pytest.MonkeyPatch) -> None:
    """現在値取得（ライブ、yfinance）をテストでは決定的にする（既定は取得失敗扱い）."""

    async def fake_fetch_quote(_symbol: str) -> tuple[float | None, float | None, list[float]]:
        return None, None, []

    monkeypatch.setattr(sp, "fetch_quote_with_spark", fake_fetch_quote)


async def test_list_shadow_picks_returns_empty_when_no_rows(migrated_db: Path) -> None:
    assert await sp.list_shadow_picks() == []


async def test_list_shadow_picks_maps_payload_fields(migrated_db: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_fetch_quote(symbol: str) -> tuple[float | None, float | None, list[float]]:
        assert symbol == "7203"
        return 1020.0, 1000.0, [1000.0, 1010.0, 1020.0]

    monkeypatch.setattr(sp, "fetch_quote_with_spark", fake_fetch_quote)

    await _seed_pick("pick-1", "7203")
    await insert_shadow_prediction(
        pick_id="pick-1",
        run_id="run-1",
        challenger_version="gemini:gemini-2.5-pro",
        symbol="7203",
        horizon_type="mid_term",
        direction="bullish",
        entry=1005.0,
        stop=960.0,
        target=1105.0,
        confidence_raw=65.0,
        confidence=65.0,
        payload={"reasoning": "テスト根拠", "risk_factors": ["為替変動"], "holding_period_days": 7},
        issued_at="2026-09-13T08:30:00+09:00",
    )

    picks = await sp.list_shadow_picks()
    assert len(picks) == 1
    pick = picks[0]
    assert pick.pick_id == "pick-1"
    assert pick.challenger_version == "gemini:gemini-2.5-pro"
    assert pick.symbol == "7203"
    assert pick.direction == "bullish"
    assert pick.entry == 1005.0
    assert pick.reasoning == "テスト根拠"
    assert pick.risk_factors == ["為替変動"]
    assert pick.holding_period_days == 7
    assert pick.current_price == 1020.0
    assert pick.change_pct == pytest.approx(2.0)
    assert pick.spark == [1000.0, 1010.0, 1020.0]


async def test_list_shadow_picks_includes_multiple_providers(migrated_db: Path) -> None:
    """🆕 マルチLLM併用: 複数プロバイダの shadow 判定が別行としてそれぞれ返る."""
    await insert_shadow_prediction(
        pick_id=None,
        run_id="run-1",
        challenger_version="gemini:gemini-2.5-pro",
        symbol="7203",
        horizon_type="mid_term",
        direction="bullish",
        entry=1000.0,
        stop=950.0,
        target=1100.0,
        confidence_raw=60.0,
        confidence=60.0,
        payload={},
    )
    await insert_shadow_prediction(
        pick_id=None,
        run_id="run-1",
        challenger_version="openai:gpt-5.1",
        symbol="7203",
        horizon_type="mid_term",
        direction="bullish",
        entry=1002.0,
        stop=955.0,
        target=1090.0,
        confidence_raw=58.0,
        confidence=58.0,
        payload={},
    )

    picks = await sp.list_shadow_picks()
    assert {p.challenger_version for p in picks} == {"gemini:gemini-2.5-pro", "openai:gpt-5.1"}


async def test_list_shadow_picks_filters_by_horizon_type(migrated_db: Path) -> None:
    await insert_shadow_prediction(
        pick_id=None,
        run_id="run-mid",
        challenger_version="gemini:gemini-2.5-pro",
        symbol="7203",
        horizon_type="mid_term",
        direction="bullish",
        entry=1000.0,
        stop=950.0,
        target=1100.0,
        confidence_raw=60.0,
        confidence=60.0,
        payload={},
    )
    await insert_shadow_prediction(
        pick_id=None,
        run_id="run-short",
        challenger_version="gemini:gemini-2.5-pro",
        symbol="9984",
        horizon_type="short_term",
        direction="bearish",
        entry=500.0,
        stop=520.0,
        target=470.0,
        confidence_raw=55.0,
        confidence=55.0,
        payload={},
    )

    mid_only = await sp.list_shadow_picks(horizon_type="mid_term")
    assert {p.symbol for p in mid_only} == {"7203"}


async def test_list_shadow_picks_handles_missing_optional_payload_fields(migrated_db: Path) -> None:
    await insert_shadow_prediction(
        pick_id=None,
        run_id="run-1",
        challenger_version="gemini:gemini-2.5-pro",
        symbol="7203",
        horizon_type="mid_term",
        direction="neutral",
        entry=1000.0,
        stop=950.0,
        target=1100.0,
        confidence_raw=50.0,
        confidence=50.0,
        payload={},
    )

    picks = await sp.list_shadow_picks()
    assert picks[0].reasoning is None
    assert picks[0].risk_factors == []
    assert picks[0].holding_period_days is None
