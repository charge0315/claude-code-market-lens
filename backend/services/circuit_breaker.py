"""単一プロセス用の軽量サーキットブレーカ.

Market Lens `backend/services/circuit_breaker.py` から移植（変更なし）。
連続失敗がしきい値に達すると OPEN になり、クールダウン中の呼び出しはネットワーク待ちを
発生させずに即 fast-fail する。送出する例外型は `open_error_factory` で注入するため、
J-Quants / yfinance 各ドメインが `CircuitOpenError` をサブクラス化して使う。
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable


class CircuitOpenError(Exception):
    """サーキットブレーカ OPEN 時の fast-fail 用汎用例外（ドメインはこれをサブクラス化する）."""

    def __init__(self, retry_after: float) -> None:
        self.retry_after = retry_after
        super().__init__(f"Circuit open (retry after {retry_after:.1f}s)")


class CircuitBreaker:
    """失敗回数しきい値 + クールダウンによる軽量サーキットブレーカ（単一プロセス用）."""

    def __init__(
        self,
        *,
        failure_threshold: int = 5,
        cooldown_sec: float = 30.0,
        open_error_factory: Callable[[float], CircuitOpenError] = CircuitOpenError,
    ) -> None:
        self._failure_threshold = failure_threshold
        self._cooldown_sec = cooldown_sec
        self._failure_count = 0
        self._opened_at: float | None = None
        self._open_error_factory = open_error_factory
        # HALF_OPEN で「試行を 1 回だけ通す」を強制するガード。同期（yfinance）・非同期
        # （J-Quants）両方から使うため asyncio.Lock ではなく threading.Lock を使う。
        self._lock = threading.Lock()
        self._half_open_trial_in_flight = False

    def before_request(self) -> None:
        """OPEN 状態でクールダウン中、または HALF_OPEN で既に試行中なら即 fast-fail する."""
        with self._lock:
            if self._opened_at is None:
                return  # CLOSED
            if time.monotonic() - self._opened_at < self._cooldown_sec:
                raise self._open_error_factory(self._remaining_cooldown())
            # クールダウン経過 → HALF_OPEN。既に 1 件試行中なら追加試行は通さない。
            if self._half_open_trial_in_flight:
                raise self._open_error_factory(self._remaining_cooldown())
            self._half_open_trial_in_flight = True

    def record_success(self) -> None:
        """成功時にカウンタと OPEN 状態をリセットし CLOSED へ戻す."""
        with self._lock:
            self._failure_count = 0
            self._opened_at = None
            self._half_open_trial_in_flight = False

    def record_failure(self) -> None:
        """失敗を記録し、しきい値到達で OPEN（クールダウン開始）にする."""
        with self._lock:
            self._failure_count += 1
            if self._failure_count >= self._failure_threshold:
                self._opened_at = time.monotonic()
            self._half_open_trial_in_flight = False

    def _remaining_cooldown(self) -> float:
        """OPEN 状態の残りクールダウン秒（下限 0）を返す."""
        if self._opened_at is None:
            return 0.0
        return max(0.0, self._cooldown_sec - (time.monotonic() - self._opened_at))
