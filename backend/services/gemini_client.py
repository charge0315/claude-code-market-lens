"""Google Gemini API 非同期クライアント（🆕 P12、マルチLLM判定）.

Anthropic（公式パイプライン）と同じプロンプトを並行して Gemini にも投げ、根拠・確信度・
買値/損切り価格/売値を「別視点の比較材料」として得るための challenger クライアント。
`services/anthropic_client.py` と同じ forced structured-output パターンを踏襲するが、
Gemini は公式 SDK ではなく REST を直接叩く（`knowledge_search_client.py`/`jquants_client.py`
と同じ設計判断 — 依存を増やさず挙動を完全に把握できるようにするため）。

環境変数 `GEMINI_API_KEY` を設定すると有効になる。未設定なら `is_configured=False` を返し、
呼び出し元（`orchestrator._record_gemini_shadow_judgment`）がフェイルソフトできるようにする。
この判定は `shadow_predictions` へ記録するだけの表示専用情報であり、Alpha Forge の
「モデル昇格・確度較正・自動売買判定は Anthropic の公式パイプラインのみで決定する」という
既存アーキテクチャには一切影響しない。
"""

from __future__ import annotations

import json
import logging
from typing import cast

import httpx

from backend.config import settings
from backend.services.circuit_breaker import CircuitBreaker
from backend.services.gemini_errors import (
    GeminiAuthError,
    GeminiCircuitOpenError,
    GeminiConnectionError,
    GeminiError,
    GeminiRateLimitError,
    GeminiResponseError,
    GeminiServerError,
    GeminiTimeoutError,
)

logger = logging.getLogger(__name__)

JsonDict = dict[str, object]

_BASE_URL = "https://generativelanguage.googleapis.com/v1beta"
_TIMEOUT = httpx.Timeout(connect=5.0, read=30.0, write=5.0, pool=5.0)

# Anthropic の _TOOL_SCHEMA（`anthropic_client.py`）と同じ項目を、Gemini の
# responseSchema（OpenAPI サブセット、大文字型名が必須）で表現する。
_STOCK_PICK_RESPONSE_SCHEMA: JsonDict = {
    "type": "OBJECT",
    "properties": {
        "should_include": {
            "type": "BOOLEAN",
            "description": "詳細分析の結果、おすすめ銘柄として提示すべきでないと判断した場合は false",
        },
        "buy_price": {"type": "NUMBER", "description": "推奨買値（円）"},
        "stop_loss_price": {"type": "NUMBER", "description": "推奨損切り価格（円）。現在値より低い値。"},
        "take_profit_price": {"type": "NUMBER", "description": "推奨売値/利確目標（円）。現在値より高い値。"},
        "confidence": {"type": "NUMBER", "description": "この提案への確信度 0-100"},
        "holding_period_days": {"type": "INTEGER", "description": "想定保有期間（営業日）"},
        "reasoning": {"type": "STRING", "description": "日本語での提案根拠（2〜4文）"},
        "risk_factors": {
            "type": "ARRAY",
            "items": {"type": "STRING"},
            "description": "主なリスク要因（日本語、箇条書き）",
        },
    },
    "required": ["should_include", "buy_price", "stop_loss_price", "take_profit_price", "confidence", "reasoning"],
}

# `anthropic_client._PORTFOLIO_SIGNAL_TOOL_SCHEMA` と同じ項目を Gemini の responseSchema で
# 表現する（🆕、保有銘柄の AI 売買タイミング判定を Claude と並行して challenger 判定させる）。
_PORTFOLIO_SIGNAL_RESPONSE_SCHEMA: JsonDict = {
    "type": "OBJECT",
    "properties": {
        "action": {
            "type": "STRING",
            "enum": ["hold", "trim", "stop_loss", "add"],
            "description": "hold=継続保有 / trim=一部利確 / stop_loss=損切り / add=買い増し",
        },
        "entry": {"type": "NUMBER", "description": "買い増し時の推奨買値（円）。action=add のときのみ使用する。"},
        "stop_loss_price": {"type": "NUMBER", "description": "更新後の損切り価格（円）。現在値より低い値。"},
        "take_profit_price": {"type": "NUMBER", "description": "更新後の利確目標（円）。現在値より高い値。"},
        "confidence": {"type": "NUMBER", "description": "この判定への確信度 0-100"},
        "reasoning": {"type": "STRING", "description": "日本語での判定根拠（2〜4文）"},
    },
    "required": ["action", "stop_loss_price", "take_profit_price", "confidence", "reasoning"],
}


class GeminiClient:
    """Gemini API の非同期シングルトンクライアント（`AnthropicClient` と同じ形）."""

    _instance: GeminiClient | None = None
    _ready: bool = False

    def __new__(cls) -> GeminiClient:
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._ready = False
        return cls._instance

    def __init__(self) -> None:
        if self._ready:
            return
        self._breaker = CircuitBreaker(open_error_factory=GeminiCircuitOpenError)
        self._ready = True

    @property
    def is_configured(self) -> bool:
        """必要な環境変数が設定されているかを返す."""
        return bool(settings.gemini_api_key)

    def _translate_and_record_failure(self, exc: Exception, context: str) -> GeminiError:
        """raw な httpx 例外を型付き例外へ翻訳する（`anthropic_client.py` と同じ方針）.

        401/403（キー失効等の永続的な設定問題）はブレーカを開かない。それ以外の
        トランスポート障害のみ `record_failure()` する。
        """
        if isinstance(exc, httpx.TimeoutException):
            self._breaker.record_failure()
            return GeminiTimeoutError(context)
        if isinstance(exc, httpx.HTTPStatusError):
            status = exc.response.status_code
            if status in (401, 403):
                return GeminiAuthError(context, status)
            if status == 429:
                self._breaker.record_failure()
                return GeminiRateLimitError(context)
            self._breaker.record_failure()
            return GeminiServerError(context, status)
        if isinstance(exc, httpx.HTTPError):
            self._breaker.record_failure()
            return GeminiConnectionError(context)
        raise exc  # 想定外の例外はそのまま

    async def _generate_structured(
        self, *, feature: str, model: str, response_schema: JsonDict, prompt: str
    ) -> JsonDict:
        """`responseSchema` で JSON スキーマ準拠の構造化出力を強制する 1 リクエストを送る."""
        self._breaker.before_request()
        url = f"{_BASE_URL}/models/{model}:generateContent"
        payload = {
            "contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "generationConfig": {
                "responseMimeType": "application/json",
                "responseSchema": response_schema,
            },
        }
        try:
            async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
                res = await client.post(url, params={"key": settings.gemini_api_key}, json=payload)
                res.raise_for_status()
        except httpx.HTTPError as e:
            raise self._translate_and_record_failure(e, feature) from e

        self._breaker.record_success()
        body = res.json()
        try:
            text = body["candidates"][0]["content"]["parts"][0]["text"]
            parsed = json.loads(text)
        except (KeyError, IndexError, TypeError, json.JSONDecodeError) as e:
            raise GeminiResponseError(f"構造化レスポンスの解析に失敗: {feature}") from e
        if not isinstance(parsed, dict):
            raise GeminiResponseError(f"構造化レスポンスが object ではありません: {feature}")
        return cast(JsonDict, parsed)

    async def propose_stock_pick(
        self, *, ticker: str, prompt: str
    ) -> JsonDict:  # noqa: ARG002 - AnthropicClient と呼び出しシグネチャを揃える
        """forced structured-output で 1 銘柄分の買値・損切り価格・売値提案を取得する（3 値必須）."""
        return await self._generate_structured(
            feature="stock_pick_gemini",
            model=settings.gemini_model,
            response_schema=_STOCK_PICK_RESPONSE_SCHEMA,
            prompt=prompt,
        )

    async def propose_portfolio_signal(
        self, *, symbol: str, prompt: str
    ) -> JsonDict:  # noqa: ARG002 - AnthropicClient と呼び出しシグネチャを揃える
        """forced structured-output で保有 1 件の継続保有/一部利確/損切/買い増し判定を取得する."""
        return await self._generate_structured(
            feature="portfolio_signal_gemini",
            model=settings.gemini_model,
            response_schema=_PORTFOLIO_SIGNAL_RESPONSE_SCHEMA,
            prompt=prompt,
        )


# モジュールレベルのシングルトン。
gemini_client = GeminiClient()
