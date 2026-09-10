"""J-Quants クライアントの例外階層と HTTP マッピング.

Market Lens `backend/services/jquants_errors.py` から移植（import パスのみ変更）。
トランスポート層（`jquants_client._get`）が raw httpx 例外をここで定義する型付き例外へ
翻訳することで、上位は httpx 実装に依存せず「タイムアウト」「上流 5xx」「スキーマ不一致」等を
一貫して分岐できる。
"""

from __future__ import annotations

from backend.services.circuit_breaker import CircuitOpenError


def _parse_retry_after(value: str | float | None) -> float | None:
    """Retry-After ヘッダ（秒数文字列を想定）を float 秒に正規化する（不能なら None）."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(value)
    except ValueError:
        return None


class JQuantsError(Exception):
    """J-Quants クライアントの基底例外."""


class JQuantsTimeoutError(JQuantsError):
    """接続 / 読み取りタイムアウト（リトライ枯渇後に送出）."""

    def __init__(self, endpoint: str) -> None:
        self.endpoint = endpoint
        super().__init__(f"J-Quants timeout: {endpoint}")


class JQuantsConnectionError(JQuantsError):
    """ネットワーク接続エラー（Connect/Read/Network/RemoteProtocol）."""

    def __init__(self, endpoint: str) -> None:
        self.endpoint = endpoint
        super().__init__(f"J-Quants connection error: {endpoint}")


class JQuantsServerError(JQuantsError):
    """上流の 429 / 5xx（リトライ枯渇後に送出）."""

    def __init__(self, endpoint: str, status_code: int, retry_after: str | float | None = None) -> None:
        self.endpoint = endpoint
        self.status_code = status_code
        self.retry_after = _parse_retry_after(retry_after)
        super().__init__(f"J-Quants server error {status_code}: {endpoint}")


class JQuantsClientError(JQuantsError):
    """リトライ不可の 4xx（400/401/403/404/422 等）。`body` にレスポンス本文先頭を保持する."""

    def __init__(self, endpoint: str, status_code: int, body: str = "") -> None:
        self.endpoint = endpoint
        self.status_code = status_code
        self.body = body
        super().__init__(f"J-Quants client error {status_code}: {endpoint}")


class JQuantsCircuitOpenError(JQuantsError, CircuitOpenError):
    """サーキットブレーカ OPEN による fast-fail（J-Quants 固有メッセージ）."""

    def __init__(self, retry_after: float) -> None:
        self.retry_after = retry_after
        # 多重継承の協調 super() は CircuitOpenError.__init__ の引数形状と衝突するため
        # Exception を直接初期化する。
        Exception.__init__(self, f"J-Quants circuit open (retry after {retry_after:.1f}s)")


class JQuantsResponseError(JQuantsError):
    """レスポンス検証失敗（pydantic ValidationError / バッチガード違反）."""


def to_http(exc: JQuantsError) -> tuple[int, str, float | None]:
    """例外を (HTTP ステータス, クライアント向けメッセージ, Retry-After 秒) に写像する."""
    if isinstance(exc, JQuantsTimeoutError):
        return 504, "J-Quants への接続がタイムアウトしました", None
    if isinstance(exc, JQuantsCircuitOpenError):
        return 503, "J-Quants が一時的に利用できません。しばらく待って再試行してください", exc.retry_after
    if isinstance(exc, JQuantsServerError):
        if exc.status_code in (429, 503):
            return 503, "J-Quants が混雑しています。時間をおいて再試行してください", exc.retry_after
        return 502, "J-Quants 側でエラーが発生しました", None
    if isinstance(exc, JQuantsConnectionError):
        return 502, "J-Quants に接続できませんでした", None
    if isinstance(exc, JQuantsClientError):
        if exc.status_code in (401, 403):
            return 503, "J-Quants API キーが無効か権限がありません", None
        return 502, "J-Quants へのリクエストが拒否されました", None
    if isinstance(exc, JQuantsResponseError):
        return 502, "J-Quants のレスポンス形式が想定と異なります", None
    return 502, "J-Quants との通信に失敗しました", None
