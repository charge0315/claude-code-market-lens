"""公式モデル一覧APIからの候補取得（`services/llm/model_catalog.py`）の検証.

外部APIは叩かず `httpx.MockTransport` で応答を差し替える。
"""

from __future__ import annotations

from collections.abc import Iterator

import httpx
import pytest

from backend.services.llm import model_catalog


@pytest.fixture(autouse=True)
def _clear_cache() -> Iterator[None]:
    model_catalog.clear_cache()
    yield
    model_catalog.clear_cache()


def _client(handler: httpx.MockTransport) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=handler)


async def test_anthropic_follows_pagination_and_sends_key_in_header() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if "after_id" not in request.url.params:
            return httpx.Response(200, json={"data": [{"id": "claude-opus-5-5"}], "has_more": True, "last_id": "x"})
        return httpx.Response(200, json={"data": [{"id": "claude-sonnet-5"}], "has_more": False})

    async with _client(httpx.MockTransport(handler)) as client:
        ids = await model_catalog._fetch_anthropic(client, "sk-ant-test")

    assert ids == ["claude-opus-5-5", "claude-sonnet-5"]
    assert seen[0].headers["x-api-key"] == "sk-ant-test"
    assert "sk-ant-test" not in str(seen[0].url)


async def test_openai_keeps_text_models_newest_first() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "data": [
                    {"id": "gpt-5.1", "created": 100},
                    {"id": "gpt-5.2", "created": 200},
                    {"id": "text-embedding-3-large", "created": 300},
                    {"id": "gpt-4o-realtime-preview", "created": 150},
                    {"id": "whisper-1", "created": 50},
                    {"id": "o4-mini", "created": 120},
                ]
            },
        )

    async with _client(httpx.MockTransport(handler)) as client:
        ids = await model_catalog._fetch_openai(client, "sk-test")

    assert ids == ["gpt-5.2", "o4-mini", "gpt-5.1"]


async def test_gemini_keeps_generate_content_models_and_uses_header_key() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if "pageToken" not in request.url.params:
            return httpx.Response(
                200,
                json={
                    "models": [
                        {"name": "models/gemini-2.5-pro", "supportedGenerationMethods": ["generateContent"]},
                        {"name": "models/text-embedding-004", "supportedGenerationMethods": ["embedContent"]},
                    ],
                    "nextPageToken": "p2",
                },
            )
        return httpx.Response(
            200,
            json={
                "models": [
                    {"name": "models/gemini-3.8-flash", "supportedGenerationMethods": ["generateContent"]},
                    {"name": "models/gemini-2.5-flash-preview-tts", "supportedGenerationMethods": ["generateContent"]},
                    {"name": "models/nano-banana-pro-preview", "supportedGenerationMethods": ["generateContent"]},
                    {"name": "models/gemma-4-31b-it", "supportedGenerationMethods": ["generateContent"]},
                    {"name": "models/gemini-robotics-er-2-preview", "supportedGenerationMethods": ["generateContent"]},
                ]
            },
        )

    async with _client(httpx.MockTransport(handler)) as client:
        ids = await model_catalog._fetch_gemini(client, "gm-test")

    assert ids == ["gemini-3.8-flash", "gemini-2.5-pro"]
    assert seen[0].headers["x-goog-api-key"] == "gm-test"
    assert "gm-test" not in str(seen[0].url)


async def test_fetch_models_returns_none_without_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    assert await model_catalog.fetch_models("gemini") is None


async def test_fetch_models_returns_none_on_http_error_and_caches(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = 0

    async def failing(client: httpx.AsyncClient, api_key: str) -> list[str]:
        nonlocal calls
        calls += 1
        raise httpx.ConnectError("boom")

    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setitem(model_catalog._FETCHERS, "openai", ("OPENAI_API_KEY", failing))

    assert await model_catalog.fetch_models("openai") is None
    assert await model_catalog.fetch_models("openai") is None
    assert calls == 1  # 失敗結果も短時間キャッシュし、毎回タイムアウトを待たせない


async def test_fetch_all_models_includes_only_successful_providers(monkeypatch: pytest.MonkeyPatch) -> None:
    async def ok(client: httpx.AsyncClient, api_key: str) -> list[str]:
        return ["claude-opus-5-5", "claude-opus-5-5", "claude-sonnet-5"]

    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.setitem(model_catalog._FETCHERS, "anthropic", ("ANTHROPIC_API_KEY", ok))

    result = await model_catalog.fetch_all_models()

    assert result == {"anthropic": ["claude-opus-5-5", "claude-sonnet-5"]}
