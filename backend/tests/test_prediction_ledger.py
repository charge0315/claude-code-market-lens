"""予測台帳の書き込み / 参照の検証（CL-1）."""

from __future__ import annotations

from pathlib import Path

import pytest

from backend.models.pick import LedgerEntry, SubScores
from backend.services.ledger import prediction_ledger as pl


def _entry(pick_id: str, *, horizon: str = "mid_term", symbol: str = "7203", confidence: float = 72.0) -> LedgerEntry:
    return LedgerEntry(
        pick_id=pick_id,
        run_id="run-1",
        issued_at="2026-09-11T08:50:00+09:00",
        horizon_type=horizon,
        symbol=symbol,
        direction="bullish",
        entry=1002.0,
        stop=985.0,
        target=1050.0,
        sub_scores=SubScores(technical=62.0, trend=58.0, fundamental=55.0, sentiment=50.0),
        composite_score=59.4,
        concordance=0.75,
        confidence_raw=70.0,
        confidence=confidence,
        confidence_bucket=pl.confidence_bucket(confidence),
        feature_snapshot={"rsi": 41.2, "atr_14": 20.0},
        rationale_struct={"drivers": ["RSI 売られすぎ"]},
        rationale_text="RSI が売られすぎ水準で反発余地。",
        model_version="baseline-2026-09-11",
        source_contributions={"technical": {"weight_share": 0.6, "contribution": 37.2}},
        created_at="2026-09-11T08:50:01+09:00",
    )


@pytest.mark.parametrize(("conf", "bucket"), [(80.0, "high"), (50.0, "mid"), (20.0, "low")])
def test_confidence_bucket(conf: float, bucket: str) -> None:
    assert pl.confidence_bucket(conf) == bucket


async def test_insert_and_list_and_get(migrated_db: Path) -> None:
    await pl.insert_picks([_entry("p1"), _entry("p2", symbol="6758", confidence=30.0)])

    all_mid = await pl.list_picks(horizon_type="mid_term")
    assert {p.pick_id for p in all_mid} == {"p1", "p2"}
    assert all_mid[0].source_contributions  # JSON が復元されている

    high_only = await pl.list_picks(bucket="high")
    assert [p.pick_id for p in high_only] == ["p1"]

    raw = await pl.get_pick("p1")
    assert raw is not None
    assert raw["feature_snapshot"] == {"rsi": 41.2, "atr_14": 20.0}
    assert raw["symbol"] == "7203"
    assert await pl.get_pick("nope") is None


async def test_shadow_picks_excluded_by_default(migrated_db: Path) -> None:
    shadow = _entry("s1").model_copy(update={"is_shadow": True})
    await pl.insert_pick(shadow)
    assert await pl.list_picks() == []
    assert len(await pl.list_picks(include_shadow=True)) == 1


async def test_horizon_filter(migrated_db: Path) -> None:
    await pl.insert_pick(_entry("m1", horizon="mid_term"))
    await pl.insert_pick(_entry("s1", horizon="short_term"))
    assert [p.pick_id for p in await pl.list_picks(horizon_type="short_term")] == ["s1"]
