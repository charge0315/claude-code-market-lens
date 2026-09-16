"""Anthropic クライアントの例外階層と HTTP マッピング.

Market Lens `backend/services/anthropic_errors.py` から移植（変更なし）。
トランスポート層が raw な anthropic SDK 例外をここで定義する型付き例外へ翻訳することで、
上位は SDK 実装に依存せず「タイムアウト」「上流 5xx」「認証エラー」「レスポンス不正」等を
一貫して分岐できる（`jquants_errors.py` と同じ設計）。
"""

from __future__ import annotations

from backend.services.circuit_breaker import CircuitOpenError
from backend.services.llm.errors import LLMError


class AnthropicError(LLMError):
    """Anthropic クライアントの基底例外."""


class AnthropicTimeoutError(AnthropicError):
    """接続 / 読み取りタイムアウト（SDK 内蔵リトライ枯渇後に送出）."""

    def __init__(self, context: str) -> None:
        self.context = context
        super().__init__(f"Anthropic timeout: {context}")


class AnthropicConnectionError(AnthropicError):
    """ネットワーク接続エラー."""

    def __init__(self, context: str) -> None:
        self.context = context
        super().__init__(f"Anthropic connection error: {context}")


class AnthropicServerError(AnthropicError):
    """上流の 5xx（SDK 内蔵リトライ枯渇後に送出）."""

    def __init__(self, context: str, status_code: int) -> None:
        self.context = context
        self.status_code = status_code
        super().__init__(f"Anthropic server error {status_code}: {context}")


class AnthropicRateLimitError(AnthropicError):
    """429 レート制限（SDK 内蔵リトライ枯渇後に送出）."""

    def __init__(self, context: str) -> None:
        self.context = context
        super().__init__(f"Anthropic rate limited: {context}")


class AnthropicAuthError(AnthropicError):
    """401 / 403 — API キー未設定・無効・権限不足（上流障害ではなく設定問題）."""

    def __init__(self, context: str, status_code: int) -> None:
        self.context = context
        self.status_code = status_code
        super().__init__(f"Anthropic auth error {status_code}: {context}")


class AnthropicCircuitOpenError(AnthropicError, CircuitOpenError):
    """サーキットブレーカ OPEN による fast-fail（Anthropic 固有メッセージ）."""

    def __init__(self, retry_after: float) -> None:
        self.retry_after = retry_after
        Exception.__init__(self, f"Anthropic circuit open (retry after {retry_after:.1f}s)")


class AnthropicResponseError(AnthropicError):
    """レスポンス検証失敗（tool_use ブロック欠如等）."""


def to_http(exc: AnthropicError) -> tuple[int, str, float | None]:
    """例外を (HTTP ステータス, クライアント向けメッセージ, Retry-After 秒) に写像する."""
    if isinstance(exc, AnthropicTimeoutError):
        return 504, "AI 分析がタイムアウトしました", None
    if isinstance(exc, AnthropicCircuitOpenError):
        return 503, "AI 分析が一時的に利用できません。しばらく待って再試行してください", exc.retry_after
    if isinstance(exc, AnthropicRateLimitError):
        return 503, "AI 分析が混雑しています。時間をおいて再試行してください", None
    if isinstance(exc, AnthropicServerError):
        return 502, "AI 分析側でエラーが発生しました", None
    if isinstance(exc, AnthropicConnectionError):
        return 502, "AI 分析に接続できませんでした", None
    if isinstance(exc, AnthropicAuthError):
        return 503, "Anthropic API キーが無効か権限がありません", None
    if isinstance(exc, AnthropicResponseError):
        return 502, "AI 分析のレスポンス形式が想定と異なります", None
    return 502, "AI 分析との通信に失敗しました", None
