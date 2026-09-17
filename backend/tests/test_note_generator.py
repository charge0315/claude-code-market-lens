"""`services/notes/note_generator` の検証（entry/stop/target を含めないこと、フェイルソフト、
4分析内訳・情報源内訳・リスク要因を詳細に含めること）."""

from __future__ import annotations

import pytest

from backend.services.notes import note_generator as gen
from backend.services.notes.note_generator import PickAnalysis


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


def _pick(symbol: str, **overrides: object) -> PickAnalysis:
    defaults: dict[str, object] = {
        "symbol": symbol,
        "company_name": "テスト株式会社",
        "direction": "bullish",
        "composite_score": 61.3,
        "confidence": 58.0,
        "confidence_bucket": "mid",
        "concordance": 1.0,
        "rationale_text": "MACDがゴールデンクロス",
        "reasoning_tags": ["MACD ゴールデンクロス"],
        "sub_scores": {"technical": 62.0, "trend": 55.0, "fundamental": 60.0, "sentiment": 50.0},
        "source_contributions": {
            "technical": {"weight_share": 0.6364, "contribution": 39.45, "score": 62.0},
            "fundamental": {"weight_share": 0.3636, "contribution": 21.82, "score": 60.0},
        },
        "llm_risk_factors": ["金利上昇リスク"],
        "holding_period_days": 10,
    }
    defaults.update(overrides)
    return PickAnalysis(**defaults)  # type: ignore[arg-type]


def test_build_prompt_excludes_entry_stop_target() -> None:
    """3値（entry/stop/target）は PickAnalysis 自体に無く、プロンプトにも一切含まれない."""
    pick = _pick("7203")

    prompt = gen.build_prompt("2026-09-17", [pick], [])

    assert "7203" in prompt
    assert "MACDがゴールデンクロス" in prompt


def test_build_prompt_includes_sub_scores_and_source_contributions() -> None:
    """根拠を詳細に・情報源を明示する（ユーザー指示）ため、4分析内訳・寄与度をプロンプトへ含める."""
    pick = _pick("7203")

    prompt = gen.build_prompt("2026-09-17", [pick], [])

    assert "テクニカル=62" in prompt
    assert "寄与度64%" in prompt
    assert "金利上昇リスク" in prompt
    assert "10営業日" in prompt


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


async def test_generate_appends_disclaimer_and_sources_note_on_success(monkeypatch: pytest.MonkeyPatch) -> None:
    long_body = (
        "# 本日の相場概況\n強気優勢でした。国内主要指数は寄り付きから堅調に推移し、"
        "半導体関連やハイテク株を中心に買いが優勢な展開となりました。海外市場の流れを引き継ぎ、"
        "投資家心理は総じてリスクオンの姿勢が強く、出来高も高水準で推移しています。"
        "個別銘柄では業績上振れ期待の高い企業に資金が集中し、テクニカル指標も強気シグナルを"
        "示すものが目立ちました。\n\n引き続き市況の変化には注意しつつ、堅調な展開が続くか"
        "見極めていく必要があります。"
    )
    monkeypatch.setattr(
        gen,
        "resolve_feature_provider",
        lambda _feature: _FakeLLM({"title": "本日の分析", "body_markdown": long_body}),
    )

    title, body, model_version = await gen.generate("2026-09-17", [_pick("7203")], [])

    assert title == "本日の分析"
    assert "強気優勢でした" in body
    assert "投資助言ではありません" in body
    assert "データソースについて" in body
    assert model_version == "anthropic:test-model"
