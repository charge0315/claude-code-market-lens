"""プロンプト挑戦者（`inference/prompt_challenger.py`）の並走の検証.

- 設定が無効なら挑戦者は一切呼ばれない（コスト・台帳ともに従来どおり）
- 有効なら、公式の採否に関係なくショートリスト銘柄を同じモデル・別プロンプトで独立に判定する
- 挑戦者の失敗・不採用は公式ピックに一切影響しない
- 挑戦者は推論トレース（銘柄詳細の AI 思考表示）を書かない
"""

from __future__ import annotations

from pathlib import Path

import pytest

from backend.models.inference import InferenceOutcome
from backend.services.anthropic_errors import AnthropicServerError
from backend.services.db import inference_trace_db as trace_db
from backend.services.inference import orchestrator as orch
from backend.services.inference import prompt_challenger as pc
from backend.tests.test_pick_pipeline import _DEFAULT_LLM, _rec

_PERSONA_MARK = "検証担当アナリスト"
_CHALLENGER_RESPONSE: dict[str, object] = {**_DEFAULT_LLM, "confidence": 64.0, "reasoning": "挑戦者の根拠"}


class _VariantAwareLLM:
    """プロンプトの版（persona-v1 か否か）で応答を切り替える LLM スタブ."""

    provider_id = "anthropic"
    is_configured = True

    def __init__(self, *, official: dict[str, object] | Exception, challenger: dict[str, object] | Exception) -> None:
        self._official = official
        self._challenger = challenger
        self.prompts: list[str] = []

    def model_for(self, feature: str) -> str:  # noqa: ARG002
        return "test-model"

    async def propose_stock_pick(self, *, ticker: str, prompt: str) -> dict[str, object]:  # noqa: ARG002
        self.prompts.append(prompt)
        resp = self._challenger if _PERSONA_MARK in prompt else self._official
        if isinstance(resp, Exception):
            raise resp
        return dict(resp)


@pytest.fixture
def isolated_sources(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _none(_code: str) -> None:
        return None

    monkeypatch.setattr(orch, "get_brand_note", _none)
    monkeypatch.setattr(orch, "get_llm_news_sentiment", _none)
    monkeypatch.setattr(orch, "resolve_shadow_providers", lambda _feature: [])


def _use(monkeypatch: pytest.MonkeyPatch, llm: _VariantAwareLLM, *, challenger: str) -> None:
    monkeypatch.setattr(orch, "resolve_feature_provider", lambda _feature: llm)
    monkeypatch.setattr(pc, "settings", pc.settings.model_copy(update={"pick_prompt_challenger": challenger}))


async def _run(*, run_challenger: bool = True) -> InferenceOutcome:
    return await orch.run_inference(
        symbol="7203",
        horizon_type="mid_term",
        batch_run_id="batch-1",
        issued_at="2026-06-01T08:50:00+09:00",
        model_version="test-model",
        rec=_rec("7203"),
        atr=20.0,
        trend_score=55.0,
        news_block=None,
        trend_block=None,
        gate_horizon=20,
        run_challenger=run_challenger,
    )


async def test_disabled_challenger_is_never_called(
    isolated_sources: None, migrated_db: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    llm = _VariantAwareLLM(official=_DEFAULT_LLM, challenger=_CHALLENGER_RESPONSE)
    _use(monkeypatch, llm, challenger="")

    outcome = await _run()

    assert len(llm.prompts) == 1
    assert outcome.challenger_pick is None


async def test_enabled_challenger_records_shadow_pick_with_variant_version(
    isolated_sources: None, migrated_db: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    llm = _VariantAwareLLM(official=_DEFAULT_LLM, challenger=_CHALLENGER_RESPONSE)
    _use(monkeypatch, llm, challenger="persona-v1")

    outcome = await _run()

    assert len(llm.prompts) == 2
    assert sum(_PERSONA_MARK in p for p in llm.prompts) == 1
    assert outcome.pick is not None and outcome.pick.is_shadow is False
    challenger = outcome.challenger_pick
    assert challenger is not None
    assert challenger.is_shadow is True
    assert challenger.model_version == "test-model+persona-v1"
    assert (challenger.symbol, challenger.run_id, challenger.issued_at) == ("7203", "batch-1", outcome.pick.issued_at)
    assert challenger.confidence_raw == 64.0
    assert challenger.rationale_text == "挑戦者の根拠"
    assert challenger.pick_id != outcome.pick.pick_id


async def test_challenger_judges_even_when_official_rejects(
    isolated_sources: None, migrated_db: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    llm = _VariantAwareLLM(official={**_DEFAULT_LLM, "should_include": False}, challenger=_CHALLENGER_RESPONSE)
    _use(monkeypatch, llm, challenger="persona-v1")

    outcome = await _run()

    assert outcome.status == "rejected" and outcome.pick is None
    assert outcome.challenger_pick is not None


async def test_challenger_judges_even_when_official_llm_fails(
    isolated_sources: None, migrated_db: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    llm = _VariantAwareLLM(official=AnthropicServerError("stock_pick", 500), challenger=_CHALLENGER_RESPONSE)
    _use(monkeypatch, llm, challenger="persona-v1")

    outcome = await _run()

    assert outcome.rejected is not None and outcome.rejected.status == "llm_error"
    assert outcome.challenger_pick is not None


async def test_challenger_failure_does_not_affect_official_pick(
    isolated_sources: None, migrated_db: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    llm = _VariantAwareLLM(official=_DEFAULT_LLM, challenger=AnthropicServerError("stock_pick", 500))
    _use(monkeypatch, llm, challenger="persona-v1")

    outcome = await _run()

    assert outcome.status == "done" and outcome.pick is not None
    assert outcome.challenger_pick is None


async def test_challenger_rejection_yields_no_shadow_pick(
    isolated_sources: None, migrated_db: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    llm = _VariantAwareLLM(official=_DEFAULT_LLM, challenger={**_DEFAULT_LLM, "should_include": False})
    _use(monkeypatch, llm, challenger="persona-v1")

    outcome = await _run()

    assert outcome.pick is not None
    assert outcome.challenger_pick is None


async def test_sandbox_style_call_skips_challenger(
    isolated_sources: None, migrated_db: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    llm = _VariantAwareLLM(official=_DEFAULT_LLM, challenger=_CHALLENGER_RESPONSE)
    _use(monkeypatch, llm, challenger="persona-v1")

    outcome = await _run(run_challenger=False)

    assert len(llm.prompts) == 1
    assert outcome.challenger_pick is None


@pytest.mark.parametrize("value", ["v1", "persona-v999"])
def test_invalid_or_champion_variant_disables_challenger(value: str, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(pc, "settings", pc.settings.model_copy(update={"pick_prompt_challenger": value}))

    assert pc.active_variant() is None


async def test_challenger_writes_no_inference_trace(
    isolated_sources: None, migrated_db: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    llm = _VariantAwareLLM(official=_DEFAULT_LLM, challenger=_CHALLENGER_RESPONSE)
    _use(monkeypatch, llm, challenger="persona-v1")

    outcome = await _run()

    runs = await trace_db.list_recent_runs(horizon_type="mid_term")
    assert [r["run_id"] for r in runs] == [outcome.run_id]
