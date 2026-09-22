"""任意銘柄のオンデマンド AI 推論トレース（🆕 P36、`services/inference/sandbox.py`）の検証.

`prediction_ledger`/`pick_pool_snapshots` を汚さないこと、`inference_traces` へ正しく記録
されること、シャドウ判定が `pick_id=None` で記録されることを中心に確認する。
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from backend.services.db import inference_trace_db as trace_db
from backend.services.db.shadow_prediction_db import list_shadow_predictions_for_run
from backend.services.inference import orchestrator as orch
from backend.services.inference import sandbox as sb
from backend.services.ledger import prediction_ledger as pl
from backend.services.picks import pipeline as pp
from backend.tests.test_pick_pipeline import _DEFAULT_LLM, WiredState, _FakeGemini, _FakeLLM, _rec


@pytest.fixture
def wired(monkeypatch: pytest.MonkeyPatch) -> WiredState:
    """`run_sandbox_inference` の外部依存をすべて差し替える（`test_pick_pipeline.wired` 相当）."""
    state = WiredState()
    fake_llm = _FakeLLM(state)
    # sandbox は起動ゲート（is_configured チェック）を自前 import で参照するため sb 側、
    # orchestrator は実呼び出し（propose_stock_pick）のため orch 側を差し替える。
    monkeypatch.setattr(sb, "resolve_feature_provider", lambda _feature: fake_llm)
    monkeypatch.setattr(orch, "resolve_feature_provider", lambda _feature: fake_llm)
    monkeypatch.setattr(orch, "resolve_shadow_providers", lambda _feature: [])

    async def fake_fundamental(code: str) -> dict[str, object]:
        return {"per": 12.0, "company_name": f"会社{code}"}

    monkeypatch.setattr(pp, "get_fundamental_with_vault_fallback", fake_fundamental)

    def fake_score_one(
        code: str, _f: dict[str, object], _provider: object = None
    ) -> tuple[dict[str, object], float | None, float | None]:
        return state.recs.get(code) or _rec(code), 20.0, 55.0

    monkeypatch.setattr(pp, "_score_one", fake_score_one)

    async def fake_panel_context(as_of: str) -> object:
        from backend.services.learning.panel_feature_service import PanelContext

        return PanelContext(as_of=as_of, frame=pd.DataFrame())

    monkeypatch.setattr(pp, "get_cached_panel_context", fake_panel_context)

    async def fake_load_champion() -> None:
        return None

    monkeypatch.setattr(pp, "load_champion_pool_classifier", fake_load_champion)

    async def fake_brand(_code: str) -> None:
        return None

    monkeypatch.setattr(orch, "get_brand_note", fake_brand)

    async def fake_news_sentiment(_code: str) -> None:
        return None

    monkeypatch.setattr(orch, "get_llm_news_sentiment", fake_news_sentiment)

    async def fake_digest() -> tuple[()]:
        return ()

    # sandbox は news_digest/trend_context を自前 import で参照するため sb 側を差し替える。
    monkeypatch.setattr(sb, "get_market_news_digest", fake_digest)
    monkeypatch.setattr(sb, "render_news_digest_block", lambda _i: None)

    async def fake_trend_ctx() -> None:
        return None

    monkeypatch.setattr(sb, "render_trend_context", fake_trend_ctx)
    return state


async def test_happy_path_does_not_write_to_prediction_ledger(wired: WiredState, migrated_db: Path) -> None:
    before = await pl.list_picks(horizon_type="mid_term", limit=200)

    outcome = await sb.run_sandbox_inference("7203", "mid_term", run_id="run-sandbox-1")

    assert outcome.status == "done"
    assert outcome.pick is not None
    after = await pl.list_picks(horizon_type="mid_term", limit=200)
    assert len(after) == len(before)  # 台帳は増えていない


async def test_happy_path_records_full_trace(wired: WiredState, migrated_db: Path) -> None:
    outcome = await sb.run_sandbox_inference("7203", "mid_term", run_id="run-sandbox-2")

    assert outcome.status == "done"
    events = await trace_db.list_trace_events("run-sandbox-2")
    assert [e["stage"] for e in events] == ["collect", "subscore", "synthesis", "llm_overlay", "bracket", "verify"]
    assert all(e["stage_status"] == "done" for e in events)


async def test_shadow_judgment_recorded_with_null_pick_id(
    wired: WiredState, migrated_db: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(orch, "resolve_shadow_providers", lambda _feature: [_FakeGemini()])

    outcome = await sb.run_sandbox_inference("7203", "mid_term", run_id="run-sandbox-3")

    assert outcome.status == "done"
    shadows = await list_shadow_predictions_for_run("run-sandbox-3")
    assert len(shadows) == 1
    assert shadows[0]["pick_id"] is None
    assert shadows[0]["challenger_version"] == "gemini:gemini-2.5-pro"


async def test_llm_not_configured_returns_rejected_without_calling_llm(
    wired: WiredState, migrated_db: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake = _FakeLLM(wired)
    fake.is_configured = False
    monkeypatch.setattr(sb, "resolve_feature_provider", lambda _feature: fake)

    outcome = await sb.run_sandbox_inference("7203", "mid_term", run_id="run-sandbox-4")

    assert outcome.status == "rejected"
    assert outcome.rejected is not None and outcome.rejected.status == "llm_error"
    # LLM 呼び出しどころかスコアリングにも進んでいないため、トレースは一切記録されない。
    assert await trace_db.list_trace_events("run-sandbox-4") == []


async def test_scoring_failure_returns_rejected(
    wired: WiredState, migrated_db: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def failing_score_one(*_a: object, **_k: object) -> None:
        raise ValueError("存在しない銘柄コード")

    monkeypatch.setattr(pp, "_score_one", failing_score_one)

    outcome = await sb.run_sandbox_inference("9999", "mid_term", run_id="run-sandbox-5")

    assert outcome.status == "rejected"
    assert outcome.rejected is not None
    assert outcome.rejected.status == "rejected_inconsistent"
    assert "存在しない銘柄コード" in outcome.rejected.reason


async def test_short_term_uses_three_day_gate_horizon(wired: WiredState, migrated_db: Path) -> None:
    """短期は決着ゲートに3営業日を使う（`pipeline.run_picks` と同じ対応）— E3実測勝率ゲートが
    正しい horizon_days でコホート勝率を引いていることを間接的に確認する."""
    wired.llm = {"7203": {**_DEFAULT_LLM, "confidence": 90.0}}

    outcome = await sb.run_sandbox_inference("7203", "short_term", run_id="run-sandbox-6")

    assert outcome.status == "done"
    assert outcome.pick is not None
    assert outcome.pick.horizon_type == "short_term"
