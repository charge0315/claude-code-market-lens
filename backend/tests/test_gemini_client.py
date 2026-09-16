"""Gemini クライアント（🆕 P12）の検証（httpx を最小フェイクでモックし、エラー翻訳を確認）.

`test_knowledge_search_client.py` と同じ「`httpx.AsyncClient` の最小互換フェイク」パターンを
踏襲する（`google-genai` 等の SDK を使わず REST を直接叩く設計のため）。
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from typing import Any

import httpx
import pytest

from backend.services import gemini_client as gc
from backend.services.circuit_breaker import CircuitBreaker
from backend.services.gemini_client import GeminiClient
from backend.services.gemini_errors import (
    GeminiAuthError,
    GeminiCircuitOpenError,
    GeminiRateLimitError,
    GeminiResponseError,
)


class _FakeResponse:
    def __init__(self, json_body: object, status_code: int = 200) -> None:
        self._json_body = json_body
        self.status_code = status_code

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            request = httpx.Request("POST", "http://x")
            raise httpx.HTTPStatusError("error", request=request, response=self)  # type: ignore[arg-type]

    def json(self) -> object:
        return self._json_body


class _FakeAsyncClient:
    """`httpx.AsyncClient` の最小互換フェイク（`async with` + `post` のみ）."""

    last_request: dict[str, Any] | None = None

    def __init__(self, response: _FakeResponse | Exception, **_kwargs: object) -> None:
        self._response = response

    async def __aenter__(self) -> _FakeAsyncClient:
        return self

    async def __aexit__(self, *_exc: object) -> bool:
        return False

    async def post(self, url: str, params: dict[str, object], json: dict[str, object]) -> _FakeResponse:
        type(self).last_request = {"url": url, "params": params, "json": json}
        if isinstance(self._response, Exception):
            raise self._response
        return self._response


def _candidate_response(payload: dict[str, object]) -> _FakeResponse:
    return _FakeResponse({"candidates": [{"content": {"parts": [{"text": json.dumps(payload)}]}}]})


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> Iterator[GeminiClient]:
    GeminiClient._instance = None
    GeminiClient._ready = False
    c = GeminiClient()
    c._breaker = CircuitBreaker(failure_threshold=1, cooldown_sec=60.0, open_error_factory=GeminiCircuitOpenError)
    monkeypatch.setattr(gc, "settings", gc.settings.model_copy(update={"gemini_api_key": "test-key"}))
    yield c
    GeminiClient._instance = None
    GeminiClient._ready = False


def _mock_client(monkeypatch: pytest.MonkeyPatch, response: _FakeResponse | Exception) -> None:
    monkeypatch.setattr(gc.httpx, "AsyncClient", lambda **kwargs: _FakeAsyncClient(response, **kwargs))


def test_is_configured_reflects_key(client: GeminiClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(gc, "settings", gc.settings.model_copy(update={"gemini_api_key": ""}))
    assert client.is_configured is False
    monkeypatch.setattr(gc, "settings", gc.settings.model_copy(update={"gemini_api_key": "sk-x"}))
    assert client.is_configured is True


def test_model_for_reflects_feature_override(client: GeminiClient, monkeypatch: pytest.MonkeyPatch) -> None:
    from backend.services.llm import registry as reg

    monkeypatch.setattr(
        reg,
        "settings",
        reg.settings.model_copy(
            update={"gemini_model": "gemini-2.5-pro", "llm_model_stock_pick_gemini": "gemini-2.5-flash"}
        ),
    )
    assert client.model_for("stock_pick") == "gemini-2.5-flash"
    assert client.model_for("portfolio_signal") == "gemini-2.5-pro"


async def test_propose_stock_pick_parses_structured_json(client: GeminiClient, monkeypatch: pytest.MonkeyPatch) -> None:
    payload = {
        "should_include": True,
        "buy_price": 100,
        "stop_loss_price": 90,
        "take_profit_price": 120,
        "confidence": 70,
        "reasoning": "テスト根拠",
    }
    _mock_client(monkeypatch, _candidate_response(payload))
    out = await client.propose_stock_pick(ticker="7203", prompt="...")
    assert out == payload


async def test_propose_portfolio_signal_parses_structured_json(
    client: GeminiClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    payload = {
        "action": "hold",
        "stop_loss_price": 950,
        "take_profit_price": 1150,
        "confidence": 65,
        "reasoning": "テスト根拠",
    }
    _mock_client(monkeypatch, _candidate_response(payload))
    out = await client.propose_portfolio_signal(symbol="7203", prompt="...")
    assert out == payload


async def test_sends_response_schema_and_api_key(client: GeminiClient, monkeypatch: pytest.MonkeyPatch) -> None:
    _mock_client(monkeypatch, _candidate_response({"should_include": False}))
    await client.propose_stock_pick(ticker="7203", prompt="prompt-text")

    sent = _FakeAsyncClient.last_request
    assert sent is not None
    assert sent["params"] == {"key": "test-key"}
    assert sent["json"]["generationConfig"]["responseMimeType"] == "application/json"
    assert "responseSchema" in sent["json"]["generationConfig"]
    assert sent["json"]["contents"][0]["parts"][0]["text"] == "prompt-text"


async def test_malformed_candidate_raises_response_error(client: GeminiClient, monkeypatch: pytest.MonkeyPatch) -> None:
    _mock_client(monkeypatch, _FakeResponse({"candidates": []}))
    with pytest.raises(GeminiResponseError):
        await client.propose_stock_pick(ticker="7203", prompt="...")


async def test_non_json_text_raises_response_error(client: GeminiClient, monkeypatch: pytest.MonkeyPatch) -> None:
    _mock_client(monkeypatch, _FakeResponse({"candidates": [{"content": {"parts": [{"text": "not json"}]}}]}))
    with pytest.raises(GeminiResponseError):
        await client.propose_stock_pick(ticker="7203", prompt="...")


async def test_rate_limit_is_translated_and_opens_circuit(
    client: GeminiClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _mock_client(monkeypatch, _FakeResponse({"error": "rate limited"}, status_code=429))
    with pytest.raises(GeminiRateLimitError):
        await client.propose_stock_pick(ticker="7203", prompt="...")
    with pytest.raises(GeminiCircuitOpenError):
        await client.propose_stock_pick(ticker="7203", prompt="...")


async def test_auth_error_does_not_open_circuit(client: GeminiClient, monkeypatch: pytest.MonkeyPatch) -> None:
    _mock_client(monkeypatch, _FakeResponse({"error": "bad key"}, status_code=401))
    with pytest.raises(GeminiAuthError):
        await client.propose_stock_pick(ticker="7203", prompt="...")
    # 401 ではブレーカを開かない → 次も AuthError（CircuitOpen ではない）。
    with pytest.raises(GeminiAuthError):
        await client.propose_stock_pick(ticker="7203", prompt="...")
