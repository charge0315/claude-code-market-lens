"""Anthropic (Claude) API 非同期クライアント.

Market Lens `backend/services/anthropic_client.py` から移植。変更点:
- P3 時点では `propose_stock_pick` / `propose_trends` / `converse` の 3 メソッドのみ移植した。
  P7b で `propose_portfolio_signal`（🆕、Market Lens に対応物なし — 保有 1 件の
  継続保有/一部利確/損切/買い増し判定）、P7d で `propose_eod_review`（🆕、Market Lens 版とは
  ツールスキーマが異なる — `portfolio_signals` の集計を要約する設計）を同じ形
  （forced tool-use + ブレーカ + api_cost 記録）で追加した。`propose_improvement_plan` は対象外
  （P5c 参照）。

環境変数 `ANTHROPIC_API_KEY` を設定すると有効になる。未設定なら `is_configured=False` を返し、
呼び出し元が「機能未設定」を返せるようにする（フェイルソフト）。forced tool-use で
JSON スキーマ準拠の構造化出力を得る。`AsyncAnthropic` SDK 自体が `max_retries` で
タイムアウト / 429 / 5xx の指数バックオフリトライを内蔵しているため手動バックオフは持たず、
サーキットブレーカによる持続障害時の fast-fail のみ独自に追加する。
"""

from __future__ import annotations

import logging
from typing import cast

import anthropic
from anthropic import AsyncAnthropic

from backend.config import settings
from backend.services import api_cost
from backend.services.anthropic_errors import (
    AnthropicAuthError,
    AnthropicCircuitOpenError,
    AnthropicConnectionError,
    AnthropicError,
    AnthropicRateLimitError,
    AnthropicResponseError,
    AnthropicServerError,
    AnthropicTimeoutError,
)
from backend.services.circuit_breaker import CircuitBreaker
from backend.services.llm.registry import resolve_model
from backend.services.llm.schemas import (
    EOD_REVIEW_SCHEMA as _EOD_REVIEW_TOOL_SCHEMA,
)
from backend.services.llm.schemas import (
    NOTE_SCHEMA as _NOTE_TOOL_SCHEMA,
)
from backend.services.llm.schemas import (
    PORTFOLIO_SIGNAL_SCHEMA as _PORTFOLIO_SIGNAL_TOOL_SCHEMA,
)
from backend.services.llm.schemas import (
    STOCK_PICK_SCHEMA as _TOOL_SCHEMA,
)
from backend.services.llm.schemas import (
    TREND_SCHEMA as _TREND_TOOL_SCHEMA,
)
from backend.services.llm.types import FeatureId

logger = logging.getLogger(__name__)

JsonDict = dict[str, object]

_MAX_TOKENS = 1024
_CHAT_MAX_TOKENS = 4096
_TREND_MAX_TOKENS = 4096
# note下書き（🆕 テンプレート準拠の多章立て記事、ユーザー指示）は _TREND_MAX_TOKENS では
# 本文が途中で切れ body_markdown が空になる事象が実測で発生したため、大きめに確保する。
_NOTE_MAX_TOKENS = 8192


class AnthropicClient:
    """Anthropic API の非同期シングルトンクライアント."""

    _instance: AnthropicClient | None = None
    _ready: bool = False

    def __new__(cls) -> AnthropicClient:
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._ready = False
        return cls._instance

    def __init__(self) -> None:
        if self._ready:
            return
        self._breaker = CircuitBreaker(open_error_factory=AnthropicCircuitOpenError)
        self._sdk: AsyncAnthropic | None = None
        self._ready = True

    provider_id = "anthropic"

    @property
    def is_configured(self) -> bool:
        """必要な環境変数が設定されているかを返す."""
        return bool(settings.anthropic_api_key)

    def model_for(self, feature: FeatureId) -> str:
        """`llm.provider.LLMProvider` プロトコル用: 指定機能で実際に使うモデルID."""
        return resolve_model(feature, "anthropic")

    def _client(self) -> AsyncAnthropic:
        if self._sdk is None:
            self._sdk = AsyncAnthropic(api_key=settings.anthropic_api_key, max_retries=2)
        return self._sdk

    def _translate_and_record_failure(self, exc: Exception, context: str) -> AnthropicError:
        """raw な anthropic SDK 例外を型付き例外へ翻訳する.

        401/403（キー失効等の永続的な設定問題）はブレーカを開かない。それ以外の
        トランスポート障害のみ `record_failure()` する（`jquants_client` と同じ方針）。
        """
        if isinstance(exc, anthropic.APITimeoutError):
            self._breaker.record_failure()
            return AnthropicTimeoutError(context)
        if isinstance(exc, anthropic.APIConnectionError):
            self._breaker.record_failure()
            return AnthropicConnectionError(context)
        if isinstance(exc, (anthropic.AuthenticationError, anthropic.PermissionDeniedError)):
            return AnthropicAuthError(context, exc.status_code)
        if isinstance(exc, anthropic.RateLimitError):
            self._breaker.record_failure()
            return AnthropicRateLimitError(context)
        if isinstance(exc, anthropic.APIStatusError):
            self._breaker.record_failure()
            return AnthropicServerError(context, exc.status_code)
        raise exc  # 想定外の例外はそのまま

    async def _forced_tool_call(
        self, *, feature: str, model: str, tool_schema: JsonDict, max_tokens: int, prompt: str
    ) -> JsonDict:
        """単一ツールを強制する 1 リクエストを送り、tool_use ブロックの input を返す.

        Market Lens では `propose_stock_pick` / `propose_trends` 等が同じ try/except を
        各メソッドで重複させていたが、Alpha Forge では移植時にここへ集約する（DRY）。
        挙動（ブレーカ・api_cost 記録・tool_use 抽出）は Market Lens と同一。
        """
        tool_name = str(tool_schema["name"])
        self._breaker.before_request()
        try:
            resp = await self._client().messages.create(
                model=model,
                max_tokens=max_tokens,
                tools=[cast("anthropic.types.ToolUnionParam", tool_schema)],
                tool_choice={"type": "tool", "name": tool_name},
                messages=[{"role": "user", "content": prompt}],
            )
        except anthropic.APIError as e:
            raise self._translate_and_record_failure(e, feature) from e

        self._breaker.record_success()
        await api_cost.record_usage(
            feature=feature, model=getattr(resp, "model", model), usage=getattr(resp, "usage", None)
        )

        tool_block = next((b for b in resp.content if b.type == "tool_use"), None)
        if tool_block is None:
            raise AnthropicResponseError(f"tool_use ブロックが見つかりません: {feature}")
        return dict(tool_block.input)

    async def propose_stock_pick(self, *, ticker: str, prompt: str) -> JsonDict:
        """forced tool-use で 1 銘柄分の買値・損切り価格・売値提案を取得する（3 値必須）."""
        return await self._forced_tool_call(
            feature="stock_pick",
            model=resolve_model("stock_pick", "anthropic"),
            tool_schema=_TOOL_SCHEMA,
            max_tokens=_MAX_TOKENS,
            prompt=prompt,
        )

    async def propose_portfolio_signal(self, *, symbol: str, prompt: str) -> JsonDict:
        """forced tool-use で保有 1 件の継続保有/一部利確/損切/買い増し判定を取得する."""
        return await self._forced_tool_call(
            feature="portfolio_signal",
            model=resolve_model("portfolio_signal", "anthropic"),
            tool_schema=_PORTFOLIO_SIGNAL_TOOL_SCHEMA,
            max_tokens=_MAX_TOKENS,
            prompt=prompt,
        )

    async def propose_eod_review(self, *, prompt: str) -> JsonDict:
        """forced tool-use で当日のポートフォリオ判定総括と学習教訓を取得する."""
        return await self._forced_tool_call(
            feature="eod_review",
            model=resolve_model("eod_review", "anthropic"),
            tool_schema=_EOD_REVIEW_TOOL_SCHEMA,
            max_tokens=_MAX_TOKENS,
            prompt=prompt,
        )

    async def propose_trends(self, *, prompt: str) -> JsonDict:
        """forced tool-use で構造化トレンド一覧（trends 配列）を取得する."""
        return await self._forced_tool_call(
            feature="trend_analyzer",
            model=resolve_model("trend_analyzer", "anthropic"),
            tool_schema=_TREND_TOOL_SCHEMA,
            max_tokens=_TREND_MAX_TOKENS,
            prompt=prompt,
        )

    async def propose_daily_note(self, *, prompt: str) -> JsonDict:
        """forced tool-use で日次noteドラフト（タイトル・本文）を取得する."""
        return await self._forced_tool_call(
            feature="note_publish",
            model=resolve_model("note_publish", "anthropic"),
            tool_schema=_NOTE_TOOL_SCHEMA,
            max_tokens=_NOTE_MAX_TOKENS,
            prompt=prompt,
        )

    async def converse(
        self,
        *,
        system: str,
        messages: list[JsonDict],
        tools: list[JsonDict],
        tool_choice: JsonDict | None = None,
        max_tokens: int | None = None,
    ) -> anthropic.types.Message:
        """チャット・テーマ株ピック等が共有する 1 ターン分のメッセージ生成.

        マルチターンのツール呼び出しループ制御は呼び出し元（`llm_tools.run_tool_loop` 等）が担い、
        このメソッドは API 呼び出し 1 回分のトランスポート層に徹する。`system` は API の専用
        パラメータとして渡す。`max_tokens` 未指定時は `_CHAT_MAX_TOKENS`。
        """
        resolved_tool_choice = (
            anthropic.omit if tool_choice is None else cast("anthropic.types.ToolChoiceParam", tool_choice)
        )
        resolved_max_tokens = max_tokens if max_tokens is not None else _CHAT_MAX_TOKENS
        self._breaker.before_request()
        try:
            resp = await self._client().messages.create(
                model=settings.anthropic_model,
                max_tokens=resolved_max_tokens,
                system=system,
                tools=cast("list[anthropic.types.ToolUnionParam]", tools),
                tool_choice=resolved_tool_choice,
                messages=cast("list[anthropic.types.MessageParam]", messages),
            )
        except anthropic.APIError as e:
            raise self._translate_and_record_failure(e, "chat") from e

        self._breaker.record_success()
        await api_cost.record_usage(
            feature="chat", model=getattr(resp, "model", settings.anthropic_model), usage=getattr(resp, "usage", None)
        )
        return resp


# モジュールレベルのシングルトン。
anthropic_client = AnthropicClient()
