"""OpenAI クライアントの検証（SDK をモックし、構造化出力抽出とエラー翻訳を確認）.

`test_anthropic_client.py` と同じ設計（SDK 呼び出しをフェイクへ差し替え、実ネットワークには
一切アクセスしない）。Responses API の Structured Outputs（`text.format.type == "json_schema"`）
を使う点のみ異なる。
"""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable, Iterator

import openai
import pytest

from backend.services import openai_client as oc
from backend.services.circuit_breaker import CircuitBreaker
from backend.services.openai_client import OpenAIClient
from backend.services.openai_errors import (
    OpenAIAuthError,
    OpenAICircuitOpenError,
    OpenAIRateLimitError,
    OpenAIResponseError,
)

_CreateFn = Callable[..., Awaitable[object]]


class _Resp:
    def __init__(self, output_text: str, model: str = "gpt-5.1") -> None:
        self.output_text = output_text
        self.model = model
        self.usage = None


class _FakeRateLimit(openai.RateLimitError):
    """SDK の RateLimitError（httpx.Response が必要）を回避する軽量サブクラス."""

    def __init__(self) -> None:
        Exception.__init__(self, "rate limited")
        self.status_code = 429


class _FakeAuthError(openai.AuthenticationError):
    def __init__(self) -> None:
        Exception.__init__(self, "bad key")
        self.status_code = 401


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> Iterator[OpenAIClient]:
    OpenAIClient._instance = None
    OpenAIClient._ready = False
    c = OpenAIClient()
    c._breaker = CircuitBreaker(failure_threshold=1, cooldown_sec=60.0, open_error_factory=OpenAICircuitOpenError)

    async def _no_cost(**_kw: object) -> None:
        return None

    monkeypatch.setattr(oc.api_cost, "record_usage", _no_cost)
    yield c
    OpenAIClient._instance = None
    OpenAIClient._ready = False


def _install_create(monkeypatch: pytest.MonkeyPatch, client: OpenAIClient, impl: _CreateFn) -> None:
    class _Responses:
        create = staticmethod(impl)

    class _SDK:
        responses = _Responses()

    monkeypatch.setattr(client, "_client", lambda: _SDK())


def test_is_configured_reflects_key(client: OpenAIClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(oc, "settings", oc.settings.model_copy(update={"openai_api_key": ""}))
    assert client.is_configured is False
    monkeypatch.setattr(oc, "settings", oc.settings.model_copy(update={"openai_api_key": "sk-x"}))
    assert client.is_configured is True


def test_model_for_reflects_feature_override(client: OpenAIClient, monkeypatch: pytest.MonkeyPatch) -> None:
    from backend.services.llm import registry as reg

    monkeypatch.setattr(
        reg,
        "settings",
        reg.settings.model_copy(update={"openai_model": "gpt-5.1", "llm_model_stock_pick_openai": "gpt-5.1-mini"}),
    )
    assert client.model_for("stock_pick") == "gpt-5.1-mini"
    assert client.model_for("portfolio_signal") == "gpt-5.1"


async def test_propose_stock_pick_parses_structured_json(client: OpenAIClient, monkeypatch: pytest.MonkeyPatch) -> None:
    payload: dict[str, object] = {
        "should_include": True,
        "buy_price": 100,
        "stop_loss_price": 90,
        "take_profit_price": 120,
        "confidence": 70,
        "holding_period_days": None,
        "reasoning": "テスト根拠",
        "risk_factors": None,
    }

    async def fake_create(**_kw: object) -> _Resp:
        return _Resp(json.dumps(payload))

    _install_create(monkeypatch, client, fake_create)
    out = await client.propose_stock_pick(ticker="7203", prompt="...")
    assert out == payload


async def test_propose_news_sentiment_parses_structured_json(
    client: OpenAIClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    payload: dict[str, object] = {
        "sentiment_label": "positive",
        "sentiment_score": 0.5,
        "impact_score": 40,
        "confidence": 55,
        "reasoning": "好調な決算見出しが複数。",
    }

    async def fake_create(**_kw: object) -> _Resp:
        return _Resp(json.dumps(payload))

    _install_create(monkeypatch, client, fake_create)
    out = await client.propose_news_sentiment(ticker="7203", prompt="...")
    assert out == payload


async def test_sends_strict_json_schema_format(client: OpenAIClient, monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    async def fake_create(**kw: object) -> _Resp:
        captured.update(kw)
        return _Resp(json.dumps({"trends": []}))

    _install_create(monkeypatch, client, fake_create)
    await client.propose_trends(prompt="prompt-text")

    assert captured["input"] == "prompt-text"
    text_format = captured["text"]["format"]  # type: ignore[index]
    assert text_format["type"] == "json_schema"
    assert text_format["strict"] is True
    assert text_format["schema"]["additionalProperties"] is False


async def test_empty_output_text_raises_response_error(client: OpenAIClient, monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_create(**_kw: object) -> _Resp:
        return _Resp("")

    _install_create(monkeypatch, client, fake_create)
    with pytest.raises(OpenAIResponseError):
        await client.propose_trends(prompt="...")


async def test_non_json_output_raises_response_error(client: OpenAIClient, monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_create(**_kw: object) -> _Resp:
        return _Resp("not json")

    _install_create(monkeypatch, client, fake_create)
    with pytest.raises(OpenAIResponseError):
        await client.propose_stock_pick(ticker="7203", prompt="...")


async def test_rate_limit_is_translated_and_opens_circuit(
    client: OpenAIClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def fake_create(**_kw: object) -> _Resp:
        raise _FakeRateLimit()

    _install_create(monkeypatch, client, fake_create)
    with pytest.raises(OpenAIRateLimitError):
        await client.propose_stock_pick(ticker="7203", prompt="...")
    with pytest.raises(OpenAICircuitOpenError):
        await client.propose_stock_pick(ticker="7203", prompt="...")


async def test_auth_error_does_not_open_circuit(client: OpenAIClient, monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_create(**_kw: object) -> _Resp:
        raise _FakeAuthError()

    _install_create(monkeypatch, client, fake_create)
    with pytest.raises(OpenAIAuthError):
        await client.propose_stock_pick(ticker="7203", prompt="...")
    # 401 ではブレーカを開かない → 次も AuthError（CircuitOpen ではない）。
    with pytest.raises(OpenAIAuthError):
        await client.propose_stock_pick(ticker="7203", prompt="...")
