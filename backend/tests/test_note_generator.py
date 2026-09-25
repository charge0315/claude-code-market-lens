"""`services/notes/note_generator` の検証（entry/stop/target を含めないこと、フェイルソフト、
4分析内訳・情報源内訳・リスク要因を詳細に含めること）."""

from __future__ import annotations

import pytest

from backend.services.notes import note_generator as gen
from backend.services.notes.note_generator import PickAnalysis, PriorOutcomeReview, review_from_row


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


def test_build_prompt_handles_no_prior_reviews() -> None:
    """前日決着分が無い日は、正直に「決着済みのピックはありません」と書かれる（捏造禁止）."""
    prompt = gen.build_prompt("2026-09-17", [], [])

    assert "直近で決着済みの検証対象銘柄はありません" in prompt


def test_build_prompt_includes_prior_review_lines() -> None:
    """前日レビュー章向けに、entry/stop/targetを含まない決着済みピックの実測値をプロンプトへ含める."""
    review = PriorOutcomeReview(
        symbol="7203",
        company_name="トヨタ自動車",
        horizon_type="short_term",
        horizon_days=1,
        direction="bullish",
        realized_return=0.021,
        excess_return=0.015,
        mfe=0.03,
        mae=-0.005,
        first_hit="target",
        win=True,
        confidence_bucket="high",
    )

    prompt = gen.build_prompt("2026-09-17", [], [], prior_reviews=[review])

    assert "7203（トヨタ自動車）" in prompt
    assert "判定=的中" in prompt
    assert "実現リターン=2.10%" in prompt
    assert "TOPIX超過リターン=1.50%" in prompt
    assert "先着=想定レンジ上限到達" in prompt
    # entry/stop/target は PriorOutcomeReview 自体に無く、プロンプトにも現れない。
    assert "entry" not in prompt.lower()


def test_review_from_row_converts_db_row() -> None:
    row = {
        "symbol": "9984",
        "company_name": "ソフトバンクグループ",
        "horizon_type": "mid_term",
        "horizon_days": 20,
        "direction": "bearish",
        "realized_return": -0.03,
        "excess_return": -0.02,
        "mfe": 0.01,
        "mae": -0.04,
        "first_hit": "stop",
        "win": 0,
        "confidence_bucket": "low",
    }

    review = review_from_row(row)

    assert review.symbol == "9984"
    assert review.win is False
    assert review.horizon_days == 20


def test_has_price_mention_detects_yen_amounts() -> None:
    assert gen.has_price_mention("本日は5680円まで上昇しました") is True
    assert gen.has_price_mention("¥5,680を回復") is True
    assert gen.has_price_mention("テクニカル的に強気の展開です") is False


async def test_generate_falls_back_when_no_picks() -> None:
    title, body, model_version = await gen.generate("2026-09-17", [], [])

    assert "分析結果がありませんでした" in body
    assert model_version == "unavailable"
    assert "投資助言・代理行為を目的としたものではありません" in body


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
    assert "投資助言・代理行為を目的としたものではありません" in body
    assert "データソースについて" in body
    assert model_version == "anthropic:test-model"


def test_build_prompt_uses_neutral_direction_label_and_term_rules() -> None:
    """方向性は売買シグナル表現（強気/買い）ではなく検証用の中立ラベルで渡す（金商法対応）."""
    prompt = gen.build_prompt("2026-09-17", [_pick("7203")], [_pick("6758", direction="bearish")])

    assert "方向性=正のトレンド相関（検証用）" in prompt
    assert "方向性=負のトレンド相関（検証用）" in prompt
    assert "方向性=強気" not in prompt
    assert "【用語規則（厳守）】" in prompt
    assert "アルゴリズム抽出銘柄" in prompt


async def test_generate_replaces_ng_terms_and_appends_fixed_disclaimer(monkeypatch: pytest.MonkeyPatch) -> None:
    body_with_ng = "本日の推奨銘柄は7203です。推奨買値・損切りライン・目標株価は記事では扱いません。" * 10
    monkeypatch.setattr(
        gen,
        "resolve_feature_provider",
        lambda _feature: _FakeLLM({"title": "本日のピック銘柄", "body_markdown": body_with_ng}),
    )

    title, body, _ = await gen.generate("2026-09-17", [_pick("7203")], [])

    assert title == "本日の検証対象銘柄"
    for ng in ("推奨銘柄", "推奨買値", "損切りライン", "目標株価"):
        assert ng not in body
    assert "アルゴリズム抽出銘柄" in body
    assert "シミュレーション起点価格" in body
    assert body.rstrip().endswith("---")
    assert "【システム検証記録に関する免責事項・注意事項】" in body
