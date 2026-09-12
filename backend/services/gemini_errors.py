"""Gemini クライアントの例外階層と HTTP マッピング（🆕 P12、マルチLLM判定）.

`services/anthropic_errors.py` と同じ設計（raw な httpx 例外をここで型付き例外へ翻訳し、
上位は「タイムアウト」「上流 5xx」「認証エラー」「レスポンス不正」等を一貫して分岐できる）。
Gemini は Anthropic 公式パイプラインと異なり表示専用の shadow 判定にのみ使うため、
失敗しても呼び出し元（`orchestrator._record_gemini_shadow_judgment`）は本体のピック生成を
止めない（フェイルソフト）。
"""

from __future__ import annotations

from backend.services.circuit_breaker import CircuitOpenError


class GeminiError(Exception):
    """Gemini クライアントの基底例外."""


class GeminiTimeoutError(GeminiError):
    """接続 / 読み取りタイムアウト."""

    def __init__(self, context: str) -> None:
        self.context = context
        super().__init__(f"Gemini timeout: {context}")


class GeminiConnectionError(GeminiError):
    """ネットワーク接続エラー."""

    def __init__(self, context: str) -> None:
        self.context = context
        super().__init__(f"Gemini connection error: {context}")


class GeminiServerError(GeminiError):
    """上流の 5xx."""

    def __init__(self, context: str, status_code: int) -> None:
        self.context = context
        self.status_code = status_code
        super().__init__(f"Gemini server error {status_code}: {context}")


class GeminiRateLimitError(GeminiError):
    """429 レート制限."""

    def __init__(self, context: str) -> None:
        self.context = context
        super().__init__(f"Gemini rate limited: {context}")


class GeminiAuthError(GeminiError):
    """401 / 403 — API キー未設定・無効・権限不足（上流障害ではなく設定問題）."""

    def __init__(self, context: str, status_code: int) -> None:
        self.context = context
        self.status_code = status_code
        super().__init__(f"Gemini auth error {status_code}: {context}")


class GeminiCircuitOpenError(GeminiError, CircuitOpenError):
    """サーキットブレーカ OPEN による fast-fail（Gemini 固有メッセージ）."""

    def __init__(self, retry_after: float) -> None:
        self.retry_after = retry_after
        Exception.__init__(self, f"Gemini circuit open (retry after {retry_after:.1f}s)")


class GeminiResponseError(GeminiError):
    """レスポンス検証失敗（構造化 JSON の解析失敗等）."""


def to_http(exc: GeminiError) -> tuple[int, str, float | None]:
    """例外を (HTTP ステータス, クライアント向けメッセージ, Retry-After 秒) に写像する."""
    if isinstance(exc, GeminiTimeoutError):
        return 504, "Gemini 判定がタイムアウトしました", None
    if isinstance(exc, GeminiCircuitOpenError):
        return 503, "Gemini 判定が一時的に利用できません。しばらく待って再試行してください", exc.retry_after
    if isinstance(exc, GeminiRateLimitError):
        return 503, "Gemini 判定が混雑しています。時間をおいて再試行してください", None
    if isinstance(exc, GeminiServerError):
        return 502, "Gemini 側でエラーが発生しました", None
    if isinstance(exc, GeminiConnectionError):
        return 502, "Gemini に接続できませんでした", None
    if isinstance(exc, GeminiAuthError):
        return 503, "Gemini API キーが無効か権限がありません", None
    if isinstance(exc, GeminiResponseError):
        return 502, "Gemini のレスポンス形式が想定と異なります", None
    return 502, "Gemini との通信に失敗しました", None
