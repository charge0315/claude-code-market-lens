"""OpenAI クライアントの例外階層と HTTP マッピング.

`services/anthropic_errors.py` と同じ設計（raw な openai SDK 例外をここで型付き例外へ翻訳し、
上位は「タイムアウト」「上流 5xx」「認証エラー」「レスポンス不正」等を一貫して分岐できる）。
"""

from __future__ import annotations

from backend.services.circuit_breaker import CircuitOpenError
from backend.services.llm.errors import LLMError


class OpenAIError(LLMError):
    """OpenAI クライアントの基底例外."""


class OpenAITimeoutError(OpenAIError):
    """接続 / 読み取りタイムアウト（SDK 内蔵リトライ枯渇後に送出）."""

    def __init__(self, context: str) -> None:
        self.context = context
        super().__init__(f"OpenAI timeout: {context}")


class OpenAIConnectionError(OpenAIError):
    """ネットワーク接続エラー."""

    def __init__(self, context: str) -> None:
        self.context = context
        super().__init__(f"OpenAI connection error: {context}")


class OpenAIServerError(OpenAIError):
    """上流の 5xx（SDK 内蔵リトライ枯渇後に送出）."""

    def __init__(self, context: str, status_code: int) -> None:
        self.context = context
        self.status_code = status_code
        super().__init__(f"OpenAI server error {status_code}: {context}")


class OpenAIRateLimitError(OpenAIError):
    """429 レート制限（SDK 内蔵リトライ枯渇後に送出）."""

    def __init__(self, context: str) -> None:
        self.context = context
        super().__init__(f"OpenAI rate limited: {context}")


class OpenAIAuthError(OpenAIError):
    """401 / 403 — API キー未設定・無効・権限不足（上流障害ではなく設定問題）."""

    def __init__(self, context: str, status_code: int) -> None:
        self.context = context
        self.status_code = status_code
        super().__init__(f"OpenAI auth error {status_code}: {context}")


class OpenAICircuitOpenError(OpenAIError, CircuitOpenError):
    """サーキットブレーカ OPEN による fast-fail（OpenAI 固有メッセージ）."""

    def __init__(self, retry_after: float) -> None:
        self.retry_after = retry_after
        Exception.__init__(self, f"OpenAI circuit open (retry after {retry_after:.1f}s)")


class OpenAIResponseError(OpenAIError):
    """レスポンス検証失敗（構造化 JSON の解析失敗等）."""


def to_http(exc: OpenAIError) -> tuple[int, str, float | None]:
    """例外を (HTTP ステータス, クライアント向けメッセージ, Retry-After 秒) に写像する."""
    if isinstance(exc, OpenAITimeoutError):
        return 504, "AI 分析がタイムアウトしました", None
    if isinstance(exc, OpenAICircuitOpenError):
        return 503, "AI 分析が一時的に利用できません。しばらく待って再試行してください", exc.retry_after
    if isinstance(exc, OpenAIRateLimitError):
        return 503, "AI 分析が混雑しています。時間をおいて再試行してください", None
    if isinstance(exc, OpenAIServerError):
        return 502, "AI 分析側でエラーが発生しました", None
    if isinstance(exc, OpenAIConnectionError):
        return 502, "AI 分析に接続できませんでした", None
    if isinstance(exc, OpenAIAuthError):
        return 503, "OpenAI API キーが無効か権限がありません", None
    if isinstance(exc, OpenAIResponseError):
        return 502, "AI 分析のレスポンス形式が想定と異なります", None
    return 502, "AI 分析との通信に失敗しました", None
