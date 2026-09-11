"""E3 実測勝率ゲートの検証（pipeline のハード除外がコホート勝率を参照する）."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from backend.models.pick import LedgerEntry, SubScores
from backend.services.db import pick_outcome_db
from backend.services.inference import orchestrator as orch
from backend.services.ledger import prediction_ledger as pl
from backend.services.picks import pipeline as pp
from backend.tests.test_pick_pipeline import WiredState, _FakeLLM, _FakeRankings, _rec  # noqa: F401


async def _seed_losing_cohort(bucket: str, direction: str, n: int = 22) -> None:
    """指定コホートに「勝率 0%」の決着を n 件仕込む（ゲート発動条件を満たす）."""
    for i in range(n):
        pid = f"seed{i}"
        await pl.insert_pick(
            LedgerEntry(
                pick_id=pid,
                run_id="seed",
                issued_at=f"2026-05-{(i % 27) + 1:02d}T08:50:00+09:00",
                horizon_type="mid_term",
                symbol=f"{8000 + i}",
                direction=direction,
                entry=1000.0,
                stop=950.0,
                target=1100.0,
                sub_scores=SubScores(technical=60, trend=55, fundamental=52, sentiment=50),
                composite_score=60.0,
                concordance=0.6,
                confidence_raw=72.0,
                confidence=72.0,
                confidence_bucket=bucket,
                feature_snapshot={},
                rationale_struct={},
                rationale_text="x",
                model_version="baseline-2026-09-11",
                source_contributions={},
                created_at="2026-05-01T08:50:01+09:00",
            )
        )
        await pick_outcome_db.upsert_outcome(
            pick_id=pid,
            horizon_days=20,
            resolved_at="2026-06-01T16:38:00+09:00",
            realized_return=-0.05,
            win=False,
            hit_stop=True,
            hit_target=False,
            first_hit="stop",
            mfe=0.0,
            mae=-0.05,
            benchmark_return=0.01,
            excess_return=-0.06,  # < 0 → 負け
            confidence_bucket=bucket,
            direction=direction,
        )


async def test_e3_gate_excludes_losing_cohort(wired: WiredState, migrated_db: Path) -> None:
    # 7203 は confidence 72 → bucket "high"、direction bullish。そのコホートを負け越しにする。
    await _seed_losing_cohort("high", "bullish")

    result = await pp.run_picks("mid_term")
    ex = [r for r in result.rejected if r.symbol == "7203"]
    assert ex and ex[0].status == "rejected_hard_excluded" and "実測勝率ゲート" in ex[0].reason


async def test_e3_gate_dormant_without_enough_samples(wired: WiredState, migrated_db: Path) -> None:
    await _seed_losing_cohort("high", "bullish", n=5)  # min_sample=20 未満 → 発動しない
    result = await pp.run_picks("mid_term")
    assert any(p.symbol == "7203" for p in result.picks)


@pytest.fixture
def wired(monkeypatch: pytest.MonkeyPatch) -> WiredState:
    """test_pick_pipeline の wired フィクスチャを再利用（同じ差し替えを行う）."""
    state = WiredState()
    fake_llm = _FakeLLM(state)
    monkeypatch.setattr(pp, "anthropic_client", fake_llm)
    monkeypatch.setattr(orch, "anthropic_client", fake_llm)

    async def fake_get_rankings(limit: int) -> _FakeRankings:  # noqa: ARG001
        return _FakeRankings(list(state.codes))

    monkeypatch.setattr(pp, "get_rankings", fake_get_rankings)

    async def fake_fundamental(code: str) -> dict[str, object]:
        return {"per": 12.0, "company_name": f"会社{code}"}

    monkeypatch.setattr(pp, "get_fundamental_with_vault_fallback", fake_fundamental)
    monkeypatch.setattr(
        pp, "_score_one", lambda code, _f, _provider=None: (state.recs.get(code) or _rec(code), 20.0, 55.0)
    )

    async def fake_brand(_code: str) -> None:
        return None

    monkeypatch.setattr(orch, "get_brand_note", fake_brand)

    async def fake_digest() -> tuple[()]:
        return ()

    monkeypatch.setattr(pp, "get_market_news_digest", fake_digest)
    monkeypatch.setattr(pp, "render_news_digest_block", lambda _i: None)

    async def fake_trend_ctx() -> None:
        return None

    monkeypatch.setattr(pp, "render_trend_context", fake_trend_ctx)

    async def fake_panel_context(as_of: str) -> object:
        from backend.services.learning.panel_feature_service import PanelContext

        return PanelContext(as_of=as_of, frame=pd.DataFrame())

    monkeypatch.setattr(pp, "get_cached_panel_context", fake_panel_context)

    async def fake_load_champion() -> None:
        return None

    monkeypatch.setattr(pp, "load_champion_pool_classifier", fake_load_champion)
    return state
