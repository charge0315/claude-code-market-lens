"""`services/notes/note_generator` の検証（entry/stop/target を含めないこと、フェイルソフト）."""

from __future__ import annotations

import pytest

from backend.models.pick import PickSummary
from backend.services.notes import note_generator as gen


class _FakeLLM:
    provider_id = "anthropic"
    is_configured = True

    def __init__(self, response: dict[str, object] | Exception) -> None:
        self._response = response

    def model_for(self, _feature: str) -> str:
        return "test-model"

    async def propose_daily_note(self, *, prompt: str) -> dict[str, object]:  # noqa: ARG002
        if isinstance(self._response, Exception):
            raise self._response
        return dict(self._response)


def _pick(symbol: str, entry: float = 9999.0, target: float = 8888.0) -> PickSummary:
    return PickSummary(
        pick_id=f"p-{symbol}",
        issued_at="2026-09-17T08:50:00+09:00",
        horizon_type="mid_term",
        symbol=symbol,
        company_name="テスト株式会社",
        direction="bullish",
        entry=entry,
        stop=1.0,
        target=target,
        composite_score=61.3,
        concordance=1.0,
        confidence=58.0,
        confidence_bucket="mid",
        rationale_text="MACDがゴールデンクロス",
        model_version="baseline-2026-09-11",
        source_contributions={},
        reasoning_tags=["MACD ゴールデンクロス"],
    )


def test_build_prompt_excludes_entry_stop_target() -> None:
    """3値（entry/stop/target）はプロンプトに一切含めない."""
    pick = _pick("7203", entry=123456.0, target=654321.0)

    prompt = gen.build_prompt("2026-09-17", [pick], [])

    assert "123456" not in prompt
    assert "654321" not in prompt
    assert "7203" in prompt
    assert "MACDがゴールデンクロス" in prompt


def test_build_prompt_handles_empty_horizon() -> None:
    prompt = gen.build_prompt("2026-09-17", [], [])

    assert "該当なし" in prompt


def test_has_price_mention_detects_yen_amounts() -> None:
    assert gen.has_price_mention("本日は5680円まで上昇しました") is True
    assert gen.has_price_mention("¥5,680を回復") is True
    assert gen.has_price_mention("テクニカル的に強気の展開です") is False


async def test_generate_falls_back_when_no_picks() -> None:
    title, body, model_version = await gen.generate("2026-09-17", [], [])

    assert "分析結果がありませんでした" in body
    assert model_version == "unavailable"
    assert "投資助言ではありません" in body


async def test_generate_falls_back_when_llm_not_configured(monkeypatch: pytest.MonkeyPatch) -> None:
    class _Unconfigured(_FakeLLM):
        is_configured = False

    monkeypatch.setattr(gen, "resolve_feature_provider", lambda _feature: _Unconfigured({}))

    title, body, model_version = await gen.generate("2026-09-17", [_pick("7203")], [])

    assert model_version == "unavailable"


async def test_generate_falls_back_on_llm_error(monkeypatch: pytest.MonkeyPatch) -> None:
    from backend.services.anthropic_errors import AnthropicRateLimitError

    monkeypatch.setattr(
        gen, "resolve_feature_provider", lambda _feature: _FakeLLM(AnthropicRateLimitError("note_publish"))
    )

    title, body, model_version = await gen.generate("2026-09-17", [_pick("7203")], [])

    assert "生成できませんでした" in body
    assert model_version == "anthropic:error"


async def test_generate_appends_disclaimer_on_success(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        gen,
        "resolve_feature_provider",
        lambda _feature: _FakeLLM({"title": "本日の分析", "body_markdown": "# 本日の相場概況\n強気優勢でした。"}),
    )

    title, body, model_version = await gen.generate("2026-09-17", [_pick("7203")], [])

    assert title == "本日の分析"
    assert "強気優勢でした" in body
    assert "投資助言ではありません" in body
    assert model_version == "anthropic:test-model"
