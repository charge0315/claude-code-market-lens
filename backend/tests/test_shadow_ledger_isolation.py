"""挑戦者（`is_shadow=1`）の台帳行の隔離を固定する.

プロンプト挑戦者（`inference/prompt_challenger.py`）の予測は採点のために決着させるが、
公式の成績・確度較正・E3 実測勝率ゲート・評価画面・ファクター重みには混ぜてはいけない。
挑戦者の行を含めて読むのは昇格評価（`registry/promotion.compute_model_metrics`）だけ。
"""

from __future__ import annotations

from pathlib import Path

from backend.models.pick import LedgerEntry, SubScores
from backend.services.db import pick_outcome_db
from backend.services.ledger import prediction_ledger as pl
from backend.services.registry import promotion

_CHAMPION = "baseline-2026-09-11"
_CHALLENGER = "baseline-2026-09-11+persona-v1"


def _entry(pick_id: str, *, is_shadow: bool, model_version: str, issued_at: str) -> LedgerEntry:
    return LedgerEntry(
        pick_id=pick_id,
        run_id="run-1",
        issued_at=issued_at,
        horizon_type="mid_term",
        symbol="7203",
        direction="bullish",
        entry=1000.0,
        stop=950.0,
        target=1100.0,
        sub_scores=SubScores(technical=60, trend=55, fundamental=52, sentiment=50),
        composite_score=60.0,
        concordance=0.6,
        confidence_raw=72.0,
        confidence=72.0,
        confidence_bucket="high",
        feature_snapshot={},
        rationale_struct={},
        rationale_text="x",
        model_version=model_version,
        source_contributions={},
        created_at=issued_at,
        is_shadow=is_shadow,
    )


async def _outcome(pick_id: str, *, excess: float) -> None:
    await pick_outcome_db.upsert_outcome(
        pick_id=pick_id,
        horizon_days=20,
        resolved_at="2026-06-01T16:38:00+09:00",
        realized_return=excess,
        win=excess > 0,
        hit_stop=False,
        hit_target=False,
        first_hit="none",
        mfe=0.0,
        mae=0.0,
        benchmark_return=0.0,
        excess_return=excess,
        confidence_bucket="high",
        direction="bullish",
    )


async def _seed() -> None:
    await pl.insert_pick(
        _entry("official", is_shadow=False, model_version=_CHAMPION, issued_at="2026-05-01T08:50:00+09:00")
    )
    await pl.insert_pick(
        _entry("shadow", is_shadow=True, model_version=_CHALLENGER, issued_at="2026-05-01T08:50:00+09:00")
    )
    await _outcome("official", excess=0.05)
    await _outcome("shadow", excess=-0.05)


async def test_eval_rows_exclude_shadow_by_default(migrated_db: Path) -> None:
    await _seed()

    rows = await pick_outcome_db.list_resolved_for_eval(horizon_days=20)
    with_shadow = await pick_outcome_db.list_resolved_for_eval(horizon_days=20, include_shadow=True)

    assert [r["pick_id"] for r in rows] == ["official"]
    assert {r["pick_id"] for r in with_shadow} == {"official", "shadow"}


async def test_cohort_winrate_ignores_shadow_outcomes(migrated_db: Path) -> None:
    await _seed()

    win_rate, n = await pick_outcome_db.cohort_winrate(confidence_bucket="high", direction="bullish", horizon_days=20)

    assert (win_rate, n) == (1.0, 1)


async def test_missing_outcomes_include_shadow_after_official(migrated_db: Path) -> None:
    await pl.insert_pick(
        _entry("shadow-old", is_shadow=True, model_version=_CHALLENGER, issued_at="2026-05-01T08:50:00+09:00")
    )
    await pl.insert_pick(
        _entry("official-new", is_shadow=False, model_version=_CHAMPION, issued_at="2026-05-02T08:50:00+09:00")
    )

    rows = await pick_outcome_db.list_picks_with_missing_outcomes(horizon_count=3)

    # 挑戦者も決着させるが、夜間の上限を公式が優先して使えるよう公式を先に並べる
    assert [r["pick_id"] for r in rows] == ["official-new", "shadow-old"]


async def test_promotion_metrics_can_see_challenger(migrated_db: Path) -> None:
    await _seed()

    challenger = await promotion.compute_model_metrics(_CHALLENGER, horizon_days=20)
    champion = await promotion.compute_model_metrics(_CHAMPION, horizon_days=20)

    assert (challenger.sample_n, challenger.win_rate) == (1, 0.0)
    assert (champion.sample_n, champion.win_rate) == (1, 1.0)
