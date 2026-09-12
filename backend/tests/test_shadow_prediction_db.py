"""`shadow_predictions`（🆕 P12: Gemini 等 challenger LLM の比較用判定）の読み書き検証."""

from __future__ import annotations

from pathlib import Path

from backend.models.pick import LedgerEntry, SubScores
from backend.services.db.shadow_prediction_db import insert_shadow_prediction, list_shadow_predictions_for_pick
from backend.services.ledger import prediction_ledger as pl


async def _seed_pick(pick_id: str) -> None:
    await pl.insert_pick(
        LedgerEntry(
            pick_id=pick_id,
            run_id="r1",
            issued_at="2026-06-01T08:50:00+09:00",
            horizon_type="mid_term",
            symbol="7203",
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
            created_at="2026-06-01T08:50:01+09:00",
        )
    )


async def test_insert_and_list_shadow_prediction_for_pick(migrated_db: Path) -> None:
    await _seed_pick("pick-1")
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
    )

    rows = await list_shadow_predictions_for_pick("pick-1")
    assert len(rows) == 1
    row = rows[0]
    assert row["challenger_version"] == "gemini:gemini-2.5-pro"
    assert row["direction"] == "bullish"
    assert row["entry"] == 1005.0
    # JSON でシリアライズした payload が dict へ復元されること。
    assert row["payload"] == {"reasoning": "テスト根拠", "risk_factors": ["為替変動"], "holding_period_days": 7}


async def test_list_shadow_predictions_returns_empty_for_unknown_pick(migrated_db: Path) -> None:
    assert await list_shadow_predictions_for_pick("does-not-exist") == []


async def test_insert_shadow_prediction_allows_null_pick_id(migrated_db: Path) -> None:
    """`pick_id` は nullable（ピック確定前の記録は現設計では発生しないが、FK は nullable のまま維持）."""
    await insert_shadow_prediction(
        pick_id=None,
        run_id="run-2",
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
    # pick_id 無しの行は pick 紐付けの一覧には出てこない（symbol/run 単位の集計は今回対象外）。
    assert await list_shadow_predictions_for_pick("does-not-exist") == []
