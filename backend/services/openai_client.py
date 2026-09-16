"""OpenAI（ChatGPT）API 非同期クライアント.

`services/anthropic_client.py` と同じ設計（シングルトン・サーキットブレーカ・forced structured
output・api_cost 記録）で、機能ごとに選択可能な LLM プロバイダの1つとして追加する
（`services/llm/registry.py` 参照）。Responses API の Structured Outputs（`text.format` に
`json_schema` を指定、`strict: True`）で JSON スキーマ準拠の構造化出力を得る。

`llm/schemas.py` の共通スキーマ（Anthropic の `input_schema` と同じ標準 JSON Schema）を
`to_openai_strict_schema()` で strict mode 用（全プロパティ必須化 + `additionalProperties: false`）
に変換して使う。

環境変数 `OPENAI_API_KEY` を設定すると有効になる。未設定なら `is_configured=False` を返し、
呼び出し元が「機能未設定」を返せるようにする（フェイルソフト）。
"""

from __future__ import annotations

import json
import logging
from typing import cast

import openai
from openai import AsyncOpenAI

from backend.config import settings
from backend.services import api_cost
from backend.services.circuit_breaker import CircuitBreaker
from backend.services.llm.schemas import (
    EOD_REVIEW_SCHEMA,
    PORTFOLIO_SIGNAL_SCHEMA,
    STOCK_PICK_SCHEMA,
    TREND_SCHEMA,
)
from backend.services.llm.schemas import to_openai_strict_schema as _strict
from backend.services.openai_errors import (
    OpenAIAuthError,
    OpenAICircuitOpenError,
    OpenAIConnectionError,
    OpenAIError,
    OpenAIRateLimitError,
    OpenAIResponseError,
    OpenAIServerError,
    OpenAITimeoutError,
)

logger = logging.getLogger(__name__)

JsonDict = dict[str, object]

_MAX_TOKENS = 1024
_TREND_MAX_TOKENS = 4096

_STOCK_PICK_STRICT_SCHEMA: JsonDict = _strict(STOCK_PICK_SCHEMA)
_PORTFOLIO_SIGNAL_STRICT_SCHEMA: JsonDict = _strict(PORTFOLIO_SIGNAL_SCHEMA)
_EOD_REVIEW_STRICT_SCHEMA: JsonDict = _strict(EOD_REVIEW_SCHEMA)
_TREND_STRICT_SCHEMA: JsonDict = _strict(TREND_SCHEMA)


class OpenAIClient:
    """OpenAI API の非同期シングルトンクライアント（`AnthropicClient` と同じ形）."""

    _instance: OpenAIClient | None = None
    _ready: bool = False

    def __new__(cls) -> OpenAIClient:
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._ready = False
        return cls._instance

    def __init__(self) -> None:
        if self._ready:
            return
        self._breaker = CircuitBreaker(open_error_factory=OpenAICircuitOpenError)
        self._sdk: AsyncOpenAI | None = None
        self._ready = True

    provider_id = "openai"

    @property
    def is_configured(self) -> bool:
        """必要な環境変数が設定されているかを返す."""
        return bool(settings.openai_api_key)

    @property
    def model_id(self) -> str:
        """`llm.provider.LLMProvider` プロトコル用: 現在使用中のモデルID."""
        return settings.openai_model

    def _client(self) -> AsyncOpenAI:
        if self._sdk is None:
            self._sdk = AsyncOpenAI(api_key=settings.openai_api_key, max_retries=2)
        return self._sdk

    def _translate_and_record_failure(self, exc: Exception, context: str) -> OpenAIError:
        """raw な openai SDK 例外を型付き例外へ翻訳する（`anthropic_client` と同じ方針）.

        401/403（キー失効等の永続的な設定問題）はブレーカを開かない。それ以外の
        トランスポート障害のみ `record_failure()` する。
        """
        if isinstance(exc, openai.APITimeoutError):
            self._breaker.record_failure()
            return OpenAITimeoutError(context)
        if isinstance(exc, openai.APIConnectionError):
            self._breaker.record_failure()
            return OpenAIConnectionError(context)
        if isinstance(exc, (openai.AuthenticationError, openai.PermissionDeniedError)):
            return OpenAIAuthError(context, exc.status_code)
        if isinstance(exc, openai.RateLimitError):
            self._breaker.record_failure()
            return OpenAIRateLimitError(context)
        if isinstance(exc, openai.APIStatusError):
            self._breaker.record_failure()
            return OpenAIServerError(context, exc.status_code)
        raise exc  # 想定外の例外はそのまま

    async def _structured_response(
        self, *, feature: str, model: str, schema_name: str, schema: JsonDict, max_tokens: int, prompt: str
    ) -> JsonDict:
        """Responses API + Structured Outputs(strict) で 1 リクエストを送り、JSON を返す."""
        self._breaker.before_request()
        try:
            resp = await self._client().responses.create(
                model=model,
                input=prompt,
                max_output_tokens=max_tokens,
                text={
                    "format": {
                        "type": "json_schema",
                        "name": schema_name,
                        "schema": schema,
                        "strict": True,
                    }
                },
            )
        except openai.APIError as e:
            raise self._translate_and_record_failure(e, feature) from e

        self._breaker.record_success()
        await api_cost.record_usage(
            feature=feature, model=getattr(resp, "model", model), usage=getattr(resp, "usage", None)
        )

        text = getattr(resp, "output_text", None)
        if not text:
            raise OpenAIResponseError(f"構造化レスポンスが空です: {feature}")
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError as e:
            raise OpenAIResponseError(f"構造化レスポンスの解析に失敗: {feature}") from e
        if not isinstance(parsed, dict):
            raise OpenAIResponseError(f"構造化レスポンスが object ではありません: {feature}")
        return cast(JsonDict, parsed)

    async def propose_stock_pick(self, *, ticker: str, prompt: str) -> JsonDict:  # noqa: ARG002
        """forced structured-output で 1 銘柄分の買値・損切り価格・売値提案を取得する（3 値必須）."""
        return await self._structured_response(
            feature="stock_pick_openai",
            model=settings.openai_model,
            schema_name="propose_stock_pick",
            schema=_STOCK_PICK_STRICT_SCHEMA,
            max_tokens=_MAX_TOKENS,
            prompt=prompt,
        )

    async def propose_portfolio_signal(self, *, symbol: str, prompt: str) -> JsonDict:  # noqa: ARG002
        """forced structured-output で保有 1 件の継続保有/一部利確/損切/買い増し判定を取得する."""
        return await self._structured_response(
            feature="portfolio_signal_openai",
            model=settings.openai_model,
            schema_name="propose_portfolio_signal",
            schema=_PORTFOLIO_SIGNAL_STRICT_SCHEMA,
            max_tokens=_MAX_TOKENS,
            prompt=prompt,
        )

    async def propose_eod_review(self, *, prompt: str) -> JsonDict:
        """forced structured-output で当日のポートフォリオ判定総括と学習教訓を取得する."""
        return await self._structured_response(
            feature="eod_review_openai",
            model=settings.openai_model,
            schema_name="submit_eod_review",
            schema=_EOD_REVIEW_STRICT_SCHEMA,
            max_tokens=_MAX_TOKENS,
            prompt=prompt,
        )

    async def propose_trends(self, *, prompt: str) -> JsonDict:
        """forced structured-output で構造化トレンド一覧（trends 配列）を取得する."""
        return await self._structured_response(
            feature="trend_analyzer_openai",
            model=settings.openai_model,
            schema_name="submit_trends",
            schema=_TREND_STRICT_SCHEMA,
            max_tokens=_TREND_MAX_TOKENS,
            prompt=prompt,
        )


# モジュールレベルのシングルトン。
openai_client = OpenAIClient()
