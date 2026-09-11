"""推論オーケストレータ（P6 stage DAG）の検証 — trace 記録と結果の両方を確認する."""

from __future__ import annotations

from pathlib import Path

import pytest

from backend.models.inference import STAGE_ORDER, InferenceOutcome
from backend.services.db import inference_trace_db as trace_db
from backend.services.inference import orchestrator as orch
from backend.tests.test_pick_pipeline import _DEFAULT_LLM, WiredState, _FakeLLM, _rec

_ATR = 20.0
_TREND = 55.0


@pytest.fixture
def wired(monkeypatch: pytest.MonkeyPatch) -> WiredState:
    state = WiredState()
    monkeypatch.setattr(orch, "anthropic_client", _FakeLLM(state))

    async def fake_brand(_code: str) -> None:
        return None

    monkeypatch.setattr(orch, "get_brand_note", fake_brand)
    return state


async def _run(state: WiredState, *, rec: dict[str, object] | None = None) -> InferenceOutcome:
    return await orch.run_inference(
        symbol="7203",
        horizon_type="mid_term",
        batch_run_id="batch-1",
        issued_at="2026-06-01T08:50:00+09:00",
        model_version="test-model",
        rec=rec if rec is not None else _rec("7203"),
        atr=_ATR,
        trend_score=_TREND,
        news_block=None,
        trend_block=None,
        gate_horizon=20,
    )


async def test_happy_path_produces_pick_and_full_trace(wired: WiredState, migrated_db: Path) -> None:
    outcome = await _run(wired)

    assert outcome.status == "done"
    assert outcome.pick is not None
    assert outcome.rejected is None

    events = await trace_db.list_trace_events(outcome.run_id)
    assert [e["stage"] for e in events] == list(STAGE_ORDER)
    assert [e["stage_seq"] for e in events] == [1, 2, 3, 4, 5, 6]
    assert all(e["stage_status"] == "done" for e in events)
    assert events[-1]["status"] == "done"
    assert events[-1]["pick_id"] == outcome.pick.pick_id
    assert events[0]["finished_at"] is None  # 途中段階は finished_at 無し
    assert events[-1]["finished_at"] is not None
    # 確定後、全ステージ行へ pick_id が遡って紐付けられる。
    assert all(e["pick_id"] == outcome.pick.pick_id for e in events)


async def test_missing_current_price_fails_at_collect(wired: WiredState, migrated_db: Path) -> None:
    rec = _rec("7203")
    rec["technical_signals"] = {"current_price": None, "signal_agreement": "aligned"}

    outcome = await _run(wired, rec=rec)

    assert outcome.status == "rejected"
    assert outcome.rejected is not None
    assert outcome.rejected.status == "rejected_inconsistent"

    events = await trace_db.list_trace_events(outcome.run_id)
    assert [e["stage"] for e in events] == ["collect"]
    assert events[0]["stage_status"] == "failed"
    assert events[0]["status"] == "rejected"


async def test_llm_error_fails_at_llm_overlay(wired: WiredState, migrated_db: Path) -> None:
    from backend.services.anthropic_errors import AnthropicRateLimitError

    wired.llm = {"7203": AnthropicRateLimitError("stock_pick")}

    outcome = await _run(wired)

    assert outcome.status == "rejected"
    assert outcome.rejected is not None and outcome.rejected.status == "llm_error"

    events = await trace_db.list_trace_events(outcome.run_id)
    assert [e["stage"] for e in events] == ["collect", "subscore", "synthesis", "llm_overlay"]
    assert events[-1]["stage_status"] == "failed"


async def test_should_include_false_is_rejected_after_llm_overlay_done(wired: WiredState, migrated_db: Path) -> None:
    wired.llm = {"7203": {**_DEFAULT_LLM, "should_include": False}}

    outcome = await _run(wired)

    assert outcome.status == "rejected"
    assert outcome.rejected is not None and outcome.rejected.status == "rejected_hard_excluded"

    events = await trace_db.list_trace_events(outcome.run_id)
    assert [e["stage"] for e in events] == ["collect", "subscore", "synthesis", "llm_overlay"]
    # LLM 呼び出し自体は成功しているので stage_status は done、run status のみ rejected。
    assert events[-1]["stage_status"] == "done"
    assert events[-1]["status"] == "rejected"


async def test_malformed_llm_response_fails_at_llm_overlay(wired: WiredState, migrated_db: Path) -> None:
    wired.llm = {"7203": {**_DEFAULT_LLM, "confidence": "not-a-number"}}

    outcome = await _run(wired)

    assert outcome.status == "rejected"
    assert outcome.rejected is not None and outcome.rejected.status == "rejected_inconsistent"

    events = await trace_db.list_trace_events(outcome.run_id)
    assert events[-1]["stage"] == "llm_overlay"
    assert events[-1]["stage_status"] == "failed"


async def test_bracket_failure_stops_before_verify(wired: WiredState, migrated_db: Path) -> None:
    # stop >= buy_price は finalize_bracket が拒否する3値不整合。
    wired.llm = {
        "7203": {
            "should_include": True,
            "buy_price": 1000.0,
            "stop_loss_price": 1010.0,
            "take_profit_price": 1050.0,
            "confidence": 80.0,
            "reasoning": "x",
        }
    }

    outcome = await _run(wired)

    assert outcome.status == "rejected"
    assert outcome.rejected is not None and outcome.rejected.status == "rejected_inconsistent"

    events = await trace_db.list_trace_events(outcome.run_id)
    assert [e["stage"] for e in events] == ["collect", "subscore", "synthesis", "llm_overlay", "bracket"]
    assert events[-1]["stage_status"] == "failed"


async def test_e1_sell_recommendation_fails_at_verify(wired: WiredState, migrated_db: Path) -> None:
    outcome = await _run(wired, rec=_rec("7203", recommendation="SELL", direction="bearish"))

    assert outcome.status == "rejected"
    assert outcome.rejected is not None
    assert outcome.rejected.status == "rejected_hard_excluded"
    assert "SELL" in outcome.rejected.reason

    events = await trace_db.list_trace_events(outcome.run_id)
    assert [e["stage"] for e in events] == list(STAGE_ORDER)
    assert events[-1]["stage_status"] == "failed"
    assert events[-1]["status"] == "rejected"


async def test_low_confidence_after_value_trap_cap_fails_at_verify(wired: WiredState, migrated_db: Path) -> None:
    # confidence 72 -> value_trap キャップで 35 -> 確度フロア(40)未満で verify 失敗。
    outcome = await _run(wired, rec=_rec("7203", value_trap=True))

    assert outcome.status == "rejected"
    assert outcome.rejected is not None and outcome.rejected.status == "rejected_low_confidence"

    events = await trace_db.list_trace_events(outcome.run_id)
    assert events[-1]["stage"] == "verify"
    assert events[-1]["stage_status"] == "failed"


async def test_list_recent_runs_returns_latest_stage_per_run(wired: WiredState, migrated_db: Path) -> None:
    outcome = await _run(wired)

    runs = await trace_db.list_recent_runs(horizon_type="mid_term")
    matching = [r for r in runs if r["run_id"] == outcome.run_id]
    assert len(matching) == 1
    assert matching[0]["stage"] == "verify"
    assert matching[0]["status"] == "done"
