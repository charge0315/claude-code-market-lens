"""`services/picks/pick_analysis.to_pick_analysis` の検証（4分析内訳・リスク要因の抽出）."""

from __future__ import annotations

from pathlib import Path

from backend.models.pick import LedgerEntry, SubScores
from backend.services.ledger import prediction_ledger as pl
from backend.services.picks.pick_analysis import to_pick_analysis


def _entry() -> LedgerEntry:
    return LedgerEntry(
        pick_id="p1",
        run_id="r1",
        issued_at="2026-09-17T08:50:00+09:00",
        horizon_type="mid_term",
        symbol="7203",
        direction="bullish",
        entry=1002.0,
        stop=985.0,
        target=1050.0,
        sub_scores=SubScores(technical=62, trend=20, fundamental=60, sentiment=50),
        composite_score=61.3,
        concordance=1.0,
        confidence_raw=58.0,
        confidence=58.0,
        confidence_bucket="mid",
        feature_snapshot={},
        rationale_struct={
            "recommender_reasoning": ["MACDゴールデンクロス"],
            "llm_risk_factors": ["金利上昇リスク", "為替変動リスク"],
            "holding_period_days": 10,
        },
        rationale_text="MACDがゴールデンクロス",
        model_version="baseline-2026-09-11",
        source_contributions={"technical": {"weight_share": 0.64, "contribution": 39.5, "score": 62.0}},
        created_at="2026-09-17T08:50:01+09:00",
    )


async def test_to_pick_analysis_extracts_sub_scores_and_risk_factors(migrated_db: Path) -> None:
    await pl.insert_pick(_entry())
    (summary,) = await pl.list_picks(horizon_type="mid_term", limit=1)

    analysis = await to_pick_analysis(summary)

    assert analysis.pick_id == "p1"
    assert analysis.sub_scores == {"technical": 62.0, "trend": 20.0, "fundamental": 60.0, "sentiment": 50.0}
    assert analysis.llm_risk_factors == ["金利上昇リスク", "為替変動リスク"]
    assert analysis.holding_period_days == 10
    assert analysis.source_contributions == {"technical": {"weight_share": 0.64, "contribution": 39.5, "score": 62.0}}
    # entry/stop/target は PickAnalysis に存在しない（属性アクセスできないことを確認）。
    assert not hasattr(analysis, "entry")
    assert not hasattr(analysis, "stop")
    assert not hasattr(analysis, "target")


async def test_to_pick_analysis_handles_missing_raw_row_gracefully(migrated_db: Path) -> None:
    """台帳に存在しない pick_id を渡しても例外を投げずフォールバックする（フェイルソフト）."""
    from backend.models.pick import PickSummary

    summary = PickSummary(
        pick_id="does-not-exist",
        issued_at="2026-09-17T08:50:00+09:00",
        horizon_type="mid_term",
        symbol="9999",
        company_name=None,
        direction="neutral",
        entry=0.0,
        stop=0.0,
        target=0.0,
        composite_score=50.0,
        concordance=0.0,
        confidence=50.0,
        confidence_bucket="mid",
        rationale_text="x",
        model_version="v1",
        source_contributions={},
    )

    analysis = await to_pick_analysis(summary)

    assert analysis.sub_scores == {}
    assert analysis.llm_risk_factors == []
    assert analysis.holding_period_days is None
