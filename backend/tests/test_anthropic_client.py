"""Anthropic クライアントの検証（SDK をモックし、tool_use 抽出とエラー翻訳を確認）."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Iterator

import anthropic
import pytest

from backend.services import anthropic_client as ac
from backend.services.anthropic_client import AnthropicClient
from backend.services.anthropic_errors import (
    AnthropicAuthError,
    AnthropicCircuitOpenError,
    AnthropicRateLimitError,
    AnthropicResponseError,
)
from backend.services.circuit_breaker import CircuitBreaker

_CreateFn = Callable[..., Awaitable[object]]


class _ToolBlock:
    type = "tool_use"

    def __init__(self, payload: dict[str, object]) -> None:
        self.input = payload


class _TextBlock:
    type = "text"


class _Resp:
    def __init__(self, content: list[object], model: str = "claude-sonnet-5") -> None:
        self.content = content
        self.model = model
        self.usage = None


class _FakeRateLimit(anthropic.RateLimitError):
    """SDK の RateLimitError（httpx2.Response が必要）を回避する軽量サブクラス."""

    def __init__(self) -> None:
        Exception.__init__(self, "rate limited")
        self.status_code = 429


class _FakeAuthError(anthropic.AuthenticationError):
    def __init__(self) -> None:
        Exception.__init__(self, "bad key")
        self.status_code = 401


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> Iterator[AnthropicClient]:
    AnthropicClient._instance = None
    AnthropicClient._ready = False
    c = AnthropicClient()
    c._breaker = CircuitBreaker(failure_threshold=1, cooldown_sec=60.0, open_error_factory=AnthropicCircuitOpenError)

    async def _no_cost(**_kw: object) -> None:
        return None

    monkeypatch.setattr(ac.api_cost, "record_usage", _no_cost)
    yield c
    AnthropicClient._instance = None
    AnthropicClient._ready = False


def _install_create(monkeypatch: pytest.MonkeyPatch, client: AnthropicClient, impl: _CreateFn) -> None:
    class _Messages:
        create = staticmethod(impl)

    class _SDK:
        messages = _Messages()

    monkeypatch.setattr(client, "_client", lambda: _SDK())


def test_is_configured_reflects_key(client: AnthropicClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ac, "settings", ac.settings.model_copy(update={"anthropic_api_key": ""}))
    assert client.is_configured is False
    monkeypatch.setattr(ac, "settings", ac.settings.model_copy(update={"anthropic_api_key": "sk-x"}))
    assert client.is_configured is True


async def test_propose_stock_pick_returns_tool_input(client: AnthropicClient, monkeypatch: pytest.MonkeyPatch) -> None:
    payload: dict[str, object] = {
        "should_include": True,
        "buy_price": 100,
        "stop_loss_price": 90,
        "take_profit_price": 120,
    }

    async def fake_create(**_kw: object) -> _Resp:
        return _Resp([_TextBlock(), _ToolBlock(payload)])

    _install_create(monkeypatch, client, fake_create)
    out = await client.propose_stock_pick(ticker="7203", prompt="...")
    assert out == payload


async def test_propose_news_sentiment_returns_tool_input(
    client: AnthropicClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    payload: dict[str, object] = {
        "sentiment_label": "negative",
        "sentiment_score": -0.4,
        "impact_score": 55,
        "confidence": 60,
        "reasoning": "業績下方修正の見出しが複数あり弱含み。",
    }

    async def fake_create(**_kw: object) -> _Resp:
        return _Resp([_ToolBlock(payload)])

    _install_create(monkeypatch, client, fake_create)
    out = await client.propose_news_sentiment(ticker="7203", prompt="...")
    assert out == payload


def test_model_for_falls_back_to_provider_default(client: AnthropicClient, monkeypatch: pytest.MonkeyPatch) -> None:
    from backend.services.llm import registry as reg

    monkeypatch.setattr(reg, "settings", reg.settings.model_copy(update={"anthropic_model": "claude-sonnet-5"}))
    assert client.model_for("stock_pick") == "claude-sonnet-5"


def test_model_for_reflects_feature_override(client: AnthropicClient, monkeypatch: pytest.MonkeyPatch) -> None:
    from backend.services.llm import registry as reg

    monkeypatch.setattr(
        reg,
        "settings",
        reg.settings.model_copy(
            update={"anthropic_model": "claude-sonnet-5", "llm_model_stock_pick_anthropic": "claude-opus-5"}
        ),
    )
    assert client.model_for("stock_pick") == "claude-opus-5"
    assert client.model_for("portfolio_signal") == "claude-sonnet-5"


async def test_propose_stock_pick_sends_overridden_model(
    client: AnthropicClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from backend.services.llm import registry as reg

    monkeypatch.setattr(
        reg, "settings", reg.settings.model_copy(update={"llm_model_stock_pick_anthropic": "claude-opus-5"})
    )
    captured: dict[str, object] = {}

    async def fake_create(**kw: object) -> _Resp:
        captured.update(kw)
        return _Resp([_ToolBlock({"should_include": True})])

    _install_create(monkeypatch, client, fake_create)
    await client.propose_stock_pick(ticker="7203", prompt="...")
    assert captured["model"] == "claude-opus-5"


async def test_missing_tool_block_raises_response_error(
    client: AnthropicClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def fake_create(**_kw: object) -> _Resp:
        return _Resp([_TextBlock()])

    _install_create(monkeypatch, client, fake_create)
    with pytest.raises(AnthropicResponseError):
        await client.propose_trends(prompt="...")


async def test_rate_limit_is_translated_and_opens_circuit(
    client: AnthropicClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def fake_create(**_kw: object) -> _Resp:
        raise _FakeRateLimit()

    _install_create(monkeypatch, client, fake_create)
    with pytest.raises(AnthropicRateLimitError):
        await client.propose_stock_pick(ticker="7203", prompt="...")
    with pytest.raises(AnthropicCircuitOpenError):
        await client.propose_stock_pick(ticker="7203", prompt="...")


async def test_auth_error_does_not_open_circuit(client: AnthropicClient, monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_create(**_kw: object) -> _Resp:
        raise _FakeAuthError()

    _install_create(monkeypatch, client, fake_create)
    with pytest.raises(AnthropicAuthError):
        await client.propose_stock_pick(ticker="7203", prompt="...")
    # 401 ではブレーカを開かない → 次も AuthError（CircuitOpen ではない）。
    with pytest.raises(AnthropicAuthError):
        await client.propose_stock_pick(ticker="7203", prompt="...")
