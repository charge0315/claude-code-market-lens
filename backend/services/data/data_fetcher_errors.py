"""yfinance 経由の株価データ取得における例外階層.

Market Lens `backend/services/data_fetcher_errors.py` から移植（import パスのみ変更）。
`data_fetcher.fetch_stock_data` が raw な yfinance 例外をここで定義する型付き例外へ翻訳し、
呼び出し元が `str(exc)` でユーザー向け日本語メッセージを得られるようにする。
"""

from __future__ import annotations

from backend.services.circuit_breaker import CircuitOpenError


class DataFetcherError(Exception):
    """株価データ取得サービス（yfinance）の基底例外."""


class StockRateLimitError(DataFetcherError):
    """yfinance のレート制限（YFRateLimitError）でリトライが枯渇した際に送出する."""

    def __init__(self, ticker: str) -> None:
        self.ticker = ticker
        super().__init__("株価データ取得でレート制限が発生しました。しばらく待ってから再試行してください")


class StockCircuitOpenError(DataFetcherError, CircuitOpenError):
    """サーキットブレーカ OPEN による fast-fail（yfinance 固有メッセージ）."""

    def __init__(self, retry_after: float) -> None:
        self.retry_after = retry_after
        Exception.__init__(
            self,
            "株価データ取得が一時的に利用できません。しばらく待ってから再試行してください"
            f"（{retry_after:.0f}秒後に再試行可能）",
        )
