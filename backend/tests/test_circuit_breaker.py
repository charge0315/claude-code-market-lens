"""サーキットブレーカの検証（Market Lens から移植）."""

from __future__ import annotations

import pytest

from backend.services.circuit_breaker import CircuitBreaker, CircuitOpenError


def test_stays_closed_below_threshold() -> None:
    cb = CircuitBreaker(failure_threshold=3, cooldown_sec=10.0)
    cb.before_request()
    cb.record_failure()
    cb.record_failure()
    # まだ CLOSED。
    cb.before_request()


def test_opens_after_threshold_and_fast_fails_during_cooldown() -> None:
    cb = CircuitBreaker(failure_threshold=2, cooldown_sec=60.0)
    cb.record_failure()
    cb.record_failure()  # ここで OPEN。
    with pytest.raises(CircuitOpenError):
        cb.before_request()


def test_record_success_resets_to_closed() -> None:
    cb = CircuitBreaker(failure_threshold=2, cooldown_sec=60.0)
    cb.record_failure()
    cb.record_failure()
    cb.record_success()
    # CLOSED に戻り、fast-fail しない。
    cb.before_request()


def test_half_open_allows_single_trial(monkeypatch: pytest.MonkeyPatch) -> None:
    cb = CircuitBreaker(failure_threshold=1, cooldown_sec=0.0)
    cb.record_failure()  # OPEN（cooldown 0 なので即 HALF_OPEN 可）。

    # 1 回目の試行は通る。
    cb.before_request()
    # 2 回目は「試行中」なので弾かれる。
    with pytest.raises(CircuitOpenError):
        cb.before_request()
    # 試行が失敗を記録すると in-flight が解けて、次の試行がまた 1 回だけ通る。
    cb.record_failure()
    cb.before_request()


def test_domain_specific_open_error_factory() -> None:
    class MyOpen(CircuitOpenError):
        pass

    cb = CircuitBreaker(failure_threshold=1, cooldown_sec=60.0, open_error_factory=MyOpen)
    cb.record_failure()
    with pytest.raises(MyOpen):
        cb.before_request()
