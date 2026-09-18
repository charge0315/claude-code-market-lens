"""中長期 / 短期ピックパイプラインの検証（外部依存はすべてモック）."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import cast

import pandas as pd
import pytest

from backend.services.anthropic_errors import AnthropicRateLimitError
from backend.services.inference import orchestrator as orch
from backend.services.ledger import prediction_ledger as pl
from backend.services.picks import pipeline as pp

_DEFAULT_LLM: dict[str, object] = {
    "should_include": True,
    "buy_price": 1002.0,
    "stop_loss_price": 985.0,
    "take_profit_price": 1050.0,
    "confidence": 72.0,
    "reasoning": "反発余地あり",
    "holding_period_days": 7,
}


def _rec(
    code: str,
    *,
    composite: float = 62.0,
    recommendation: str = "BUY",
    direction: str = "bullish",
    value_trap: bool = False,
    agreement: str = "aligned",
    current_price: float = 1000.0,
) -> dict[str, object]:
    return {
        "ticker": code,
        "company_name": f"会社{code}",
        "recommendation": recommendation,
        "composite_score": composite,
        "concordance": 0.67,
        "direction": direction,
        "score_breakdown": {"technical": 60.0, "fundamental": 55.0, "sentiment": None},
        "source_contributions": {"technical": {"weight_share": 0.64, "contribution": 38.4}},
        "technical_signals": {"current_price": current_price, "signal_agreement": agreement},
        "fundamental_signals": {"value_trap": value_trap, "per": 12.0},
        "sentiment_average": 0.5,
        "ml_prediction_rate": None,
        "reasoning": ["RSI 売られすぎ"],
    }


class _FakeRankings:
    def __init__(self, codes: list[str]) -> None:
        self.gainers = [type("E", (), {"code": c})() for c in codes]
        self.volume_leaders: list[object] = []
        self.losers: list[object] = []


@dataclass
class WiredState:
    codes: list[str] = field(default_factory=lambda: ["7203", "6758"])
    recs: dict[str, dict[str, object]] = field(default_factory=dict)
    llm: dict[str, object] = field(default_factory=dict)  # code -> 応答 dict or Exception

    async def propose_stock_pick(self, *, ticker: str, prompt: str) -> dict[str, object]:  # noqa: ARG002
        resp = self.llm.get(ticker)
        if isinstance(resp, Exception):
            raise resp
        return resp if isinstance(resp, dict) else dict(_DEFAULT_LLM)


class _FakeLLM:
    """`llm.provider.LLMProvider` 互換の AnthropicClient スタブ."""

    provider_id = "anthropic"

    def __init__(self, state: WiredState) -> None:
        self._state = state
        self.is_configured = True

    def model_for(self, feature: str) -> str:  # noqa: ARG002
        return "test-model"

    async def propose_stock_pick(self, *, ticker: str, prompt: str) -> dict[str, object]:
        return await self._state.propose_stock_pick(ticker=ticker, prompt=prompt)


_DEFAULT_GEMINI: dict[str, object] = {
    "should_include": True,
    "buy_price": 1003.0,
    "stop_loss_price": 980.0,
    "take_profit_price": 1060.0,
    "confidence": 68.0,
    "reasoning": "Gemini 側の根拠",
    "risk_factors": ["需給悪化"],
    "holding_period_days": 6,
}


class _FakeGemini:
    """`llm.provider.LLMProvider` 互換の GeminiClient スタブ（shadow 判定用）.

    `provider_id`/`model` は複数プロバイダ併用テスト（例: OpenAI 役として流用する場合）で
    インスタンス属性として上書きできるようにしてある。
    """

    provider_id = "gemini"
    model = "gemini-2.5-pro"

    def __init__(self, response: object = None, *, configured: bool = True) -> None:
        self.is_configured = configured
        self._response = response if response is not None else dict(_DEFAULT_GEMINI)

    def model_for(self, feature: str) -> str:  # noqa: ARG002
        return self.model

    async def propose_stock_pick(self, *, ticker: str, prompt: str) -> dict[str, object]:  # noqa: ARG002
        if isinstance(self._response, Exception):
            raise self._response
        return dict(self._response) if isinstance(self._response, dict) else dict(_DEFAULT_GEMINI)


@pytest.fixture
def wired(monkeypatch: pytest.MonkeyPatch) -> WiredState:
    """パイプラインの外部依存をすべて差し替える（LLM 深掘り以降は orchestrator 側に配線する）."""
    state = WiredState()
    fake_llm = _FakeLLM(state)
    # pipeline は起動ゲート（is_configured チェック）、orchestrator は実呼び出し（propose_stock_pick）
    # でそれぞれ `resolve_feature_provider("stock_pick")` を参照しているため、両モジュールの
    # 参照先（`llm.registry` から import した関数名）を差し替える。
    monkeypatch.setattr(pp, "resolve_feature_provider", lambda _feature: fake_llm)
    monkeypatch.setattr(orch, "resolve_feature_provider", lambda _feature: fake_llm)
    # 既定では shadow プロバイダ無し（Gemini 未設定相当）として扱う（shadow 判定は
    # 明示的にテストする箇所でのみ `resolve_shadow_providers` を差し替えて有効化する）。
    monkeypatch.setattr(orch, "resolve_shadow_providers", lambda _feature: [])

    async def fake_get_rankings(limit: int) -> _FakeRankings:  # noqa: ARG001
        return _FakeRankings(list(state.codes))

    # pipeline は `from ... import get_rankings` で名前を取り込んでいるため pp 側を差し替える。
    monkeypatch.setattr(pp, "get_rankings", fake_get_rankings)

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

    # ニュースセンチメント（🆕）は既定 None（ニュース無し相当）。個別に挙動を検証する
    # テストのみ `orch.get_llm_news_sentiment` を上書きする。
    monkeypatch.setattr(orch, "get_llm_news_sentiment", fake_news_sentiment)

    async def fake_digest() -> tuple[()]:
        return ()

    monkeypatch.setattr(pp, "get_market_news_digest", fake_digest)
    monkeypatch.setattr(pp, "render_news_digest_block", lambda _i: None)

    async def fake_trend_ctx() -> None:
        return None

    monkeypatch.setattr(pp, "render_trend_context", fake_trend_ctx)
    return state


async def test_not_configured(wired: WiredState, migrated_db: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _FakeLLM(wired)
    fake.is_configured = False
    monkeypatch.setattr(pp, "resolve_feature_provider", lambda _feature: fake)
    result = await pp.run_picks("mid_term")
    assert result.status == "not_configured"
    assert result.picks == []


async def test_empty_pool(wired: WiredState, migrated_db: Path) -> None:
    wired.codes = []
    result = await pp.run_picks("mid_term")
    assert result.status == "empty"


async def test_happy_path_writes_ledger(wired: WiredState, migrated_db: Path) -> None:
    result = await pp.run_picks("mid_term")
    assert result.status == "ok"
    assert {p.symbol for p in result.picks} == {"7203", "6758"}
    for p in result.picks:
        assert p.stop < p.entry < p.target
        assert p.confidence_bucket in ("high", "mid", "low")

    stored = await pl.list_picks(horizon_type="mid_term")
    assert len(stored) == 2
    raw = await pl.get_pick(result.picks[0].pick_id)
    assert raw is not None
    assert "atr_14" in cast("dict[str, object]", raw["feature_snapshot"])


async def test_run_picks_persists_pool_snapshots(wired: WiredState, migrated_db: Path) -> None:
    """候補プール全銘柄の4分析+MLスコア・合成スコアが `pick_pool_snapshots` へ残ること（🆕 P30）."""
    from backend.services.db.pick_pool_snapshot_db import list_pool_snapshots_for_date

    result = await pp.run_picks("mid_term")

    rows = await list_pool_snapshots_for_date(result.issued_at[:10], horizon_type="mid_term")
    assert {r["symbol"] for r in rows} == {"7203", "6758"}
    # 候補が2銘柄・ショートリスト枠は12（mid_term）のため全銘柄がショートリスト入りする。
    assert all(r["is_shortlisted"] for r in rows)
    assert all(r["composite_score"] == 62.0 for r in rows)
    assert all(cast("dict[str, object]", r["score_breakdown"])["technical"] == 60.0 for r in rows)
    assert all(r["trend_score"] == 55.0 for r in rows)
    assert all(r["batch_run_id"] == result.run_id for r in rows)


async def test_e1_recommender_sell_is_hard_excluded(wired: WiredState, migrated_db: Path) -> None:
    wired.recs = {"7203": _rec("7203", recommendation="SELL", direction="bearish")}
    result = await pp.run_picks("mid_term")
    ex = [r for r in result.rejected if r.symbol == "7203"]
    assert ex and ex[0].status == "rejected_hard_excluded" and "SELL" in ex[0].reason


async def test_e2_value_trap_caps_confidence_below_floor(wired: WiredState, migrated_db: Path) -> None:
    wired.recs = {"7203": _rec("7203", value_trap=True)}
    result = await pp.run_picks("mid_term")
    ex = [r for r in result.rejected if r.symbol == "7203"]
    assert ex and ex[0].status == "rejected_low_confidence"  # 72 → 35(cap) → < 40 floor


async def test_inconsistent_bracket_rejected(wired: WiredState, migrated_db: Path) -> None:
    wired.llm = {
        "7203": {
            "should_include": True,
            "buy_price": 1002,
            "stop_loss_price": 1010,
            "take_profit_price": 1050,
            "confidence": 80,
            "reasoning": "x",
        }
    }
    result = await pp.run_picks("mid_term")
    ex = [r for r in result.rejected if r.symbol == "7203"]
    assert ex and ex[0].status == "rejected_inconsistent"


async def test_llm_error_is_recorded(wired: WiredState, migrated_db: Path) -> None:
    wired.llm = {"7203": AnthropicRateLimitError("stock_pick")}
    result = await pp.run_picks("mid_term")
    ex = [r for r in result.rejected if r.symbol == "7203"]
    assert ex and ex[0].status == "llm_error"


async def test_should_include_false_excluded(wired: WiredState, migrated_db: Path) -> None:
    wired.llm = {
        "6758": {
            "should_include": False,
            "buy_price": 1,
            "stop_loss_price": 1,
            "take_profit_price": 1,
            "confidence": 0,
            "reasoning": "x",
        }
    }
    result = await pp.run_picks("mid_term")
    ex = [r for r in result.rejected if r.symbol == "6758"]
    assert ex and ex[0].status == "rejected_hard_excluded"


async def test_gemini_shadow_judgment_recorded_after_ledger_insert(
    wired: WiredState, migrated_db: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """🆕 P12: Gemini 設定済みなら、台帳確定した各ピックについて shadow_predictions が記録される
    （`shadow_predictions.pick_id` の FK 制約上、`pl.insert_picks` の後でのみ呼べる設計）。"""
    from backend.services.db.shadow_prediction_db import list_shadow_predictions_for_pick

    monkeypatch.setattr(orch, "resolve_shadow_providers", lambda _feature: [_FakeGemini()])

    result = await pp.run_picks("mid_term")
    assert result.status == "ok"
    assert len(result.picks) == 2

    for pick in result.picks:
        rows = await list_shadow_predictions_for_pick(pick.pick_id)
        assert len(rows) == 1
        assert rows[0]["challenger_version"] == "gemini:gemini-2.5-pro"
