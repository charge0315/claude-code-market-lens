"""Google Gemini API 非同期クライアント.

公式プロバイダ（`llm.registry.resolve_feature_provider`）と同じプロンプトを並行して Gemini にも
投げ、根拠・確信度・買値/損切り価格/売値を「別視点の比較材料」として得るための challenger
クライアントとして使えるほか、機能ごとの設定次第では公式プロバイダそのものにもなり得る
（`services/llm/registry.py` 参照）。`services/anthropic_client.py` と同じ forced
structured-output パターンを踏襲するが、Gemini は公式 SDK ではなく REST を直接叩く
（`knowledge_search_client.py`/`jquants_client.py` と同じ設計判断 — 依存を増やさず挙動を
完全に把握できるようにするため）。

環境変数 `GEMINI_API_KEY` を設定すると有効になる。未設定なら `is_configured=False` を返し、
呼び出し元がフェイルソフトできるようにする。シャドウ判定として使われる場合は
`shadow_predictions`/`portfolio_signal_shadows` へ記録するだけの表示専用情報であり、
「モデル昇格・確度較正・自動売買判定は（機能ごとに選択された）公式プロバイダのみで決定する」
という既存アーキテクチャには一切影響しない。
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
from backend.services.llm.registry import resolve_model
from backend.services.llm.schemas import (
    EOD_REVIEW_SCHEMA,
    NOTE_SCHEMA,
    PORTFOLIO_SIGNAL_SCHEMA,
    STOCK_PICK_SCHEMA,
    TREND_SCHEMA,
)
from backend.services.llm.schemas import to_gemini_response_schema as _to_gemini
from backend.services.llm.types import FeatureId

logger = logging.getLogger(__name__)

JsonDict = dict[str, object]

_BASE_URL = "https://generativelanguage.googleapis.com/v1beta"
_TIMEOUT = httpx.Timeout(connect=5.0, read=30.0, write=5.0, pool=5.0)

# `llm/schemas.py` の共通スキーマ（Anthropic 形式）を Gemini の responseSchema
# （OpenAPI サブセット、大文字型名が必須）へ変換する。以前は個別に手書き複製していたが、
# 二重管理によるドリフトを避けるため `to_gemini_response_schema()` で機械変換に統一した。
_STOCK_PICK_RESPONSE_SCHEMA: JsonDict = _to_gemini(STOCK_PICK_SCHEMA)
_PORTFOLIO_SIGNAL_RESPONSE_SCHEMA: JsonDict = _to_gemini(PORTFOLIO_SIGNAL_SCHEMA)
_EOD_REVIEW_RESPONSE_SCHEMA: JsonDict = _to_gemini(EOD_REVIEW_SCHEMA)
_TREND_RESPONSE_SCHEMA: JsonDict = _to_gemini(TREND_SCHEMA)
_NOTE_RESPONSE_SCHEMA: JsonDict = _to_gemini(NOTE_SCHEMA)


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

    provider_id = "gemini"

    @property
    def is_configured(self) -> bool:
        """必要な環境変数が設定されているかを返す."""
        return bool(settings.gemini_api_key)

    def model_for(self, feature: FeatureId) -> str:
        """`llm.provider.LLMProvider` プロトコル用: 指定機能で実際に使うモデルID."""
        return resolve_model(feature, "gemini")

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
            model=resolve_model("stock_pick", "gemini"),
            response_schema=_STOCK_PICK_RESPONSE_SCHEMA,
            prompt=prompt,
        )

    async def propose_portfolio_signal(
        self, *, symbol: str, prompt: str
    ) -> JsonDict:  # noqa: ARG002 - AnthropicClient と呼び出しシグネチャを揃える
        """forced structured-output で保有 1 件の継続保有/一部利確/損切/買い増し判定を取得する."""
        return await self._generate_structured(
            feature="portfolio_signal_gemini",
            model=resolve_model("portfolio_signal", "gemini"),
            response_schema=_PORTFOLIO_SIGNAL_RESPONSE_SCHEMA,
            prompt=prompt,
        )

    async def propose_eod_review(self, *, prompt: str) -> JsonDict:
        """forced structured-output で当日のポートフォリオ判定総括と学習教訓を取得する.

        `llm.registry` により eod_review 機能の公式プロバイダとして選択された場合に使う
        （`LLMProvider` プロトコル準拠のため、Anthopic 版と同じシグネチャで用意する）。
        """
        return await self._generate_structured(
            feature="eod_review_gemini",
            model=resolve_model("eod_review", "gemini"),
            response_schema=_EOD_REVIEW_RESPONSE_SCHEMA,
            prompt=prompt,
        )

    async def propose_trends(self, *, prompt: str) -> JsonDict:
        """forced structured-output で構造化トレンド一覧（trends 配列）を取得する."""
        return await self._generate_structured(
            feature="trend_analyzer_gemini",
            model=resolve_model("trend_analyzer", "gemini"),
            response_schema=_TREND_RESPONSE_SCHEMA,
            prompt=prompt,
        )

    async def propose_daily_note(self, *, prompt: str) -> JsonDict:
        """forced structured-output で日次noteドラフト（タイトル・本文）を取得する."""
        return await self._generate_structured(
            feature="note_publish_gemini",
            model=resolve_model("note_publish", "gemini"),
            response_schema=_NOTE_RESPONSE_SCHEMA,
            prompt=prompt,
        )


# モジュールレベルのシングルトン。
gemini_client = GeminiClient()
