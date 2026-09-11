"""`tasks._is_weekday_jst` / `_is_market_hours_jst`（保有監視 beat のゲート判定）の検証."""

from __future__ import annotations

from datetime import datetime as real_datetime

import pytest

from backend import tasks
from backend.services.jst_time import JST


class _FrozenDatetime(real_datetime):
    _frozen: real_datetime

    @classmethod
    def now(cls, tz: object = None) -> real_datetime:  # type: ignore[override]  # noqa: ARG003
        return cls._frozen


def _freeze(monkeypatch: pytest.MonkeyPatch, iso: str) -> None:
    frozen = real_datetime.fromisoformat(iso)
    fake = type("_Frozen", (_FrozenDatetime,), {"_frozen": frozen})
    monkeypatch.setattr(tasks, "datetime", fake)


def test_weekday_tuesday_during_market_hours_is_true(monkeypatch: pytest.MonkeyPatch) -> None:
    _freeze(monkeypatch, "2026-06-02T10:00:00+09:00")  # 火曜
    assert tasks._is_weekday_jst() is True
    assert tasks._is_market_hours_jst() is True


def test_weekend_saturday_is_not_weekday(monkeypatch: pytest.MonkeyPatch) -> None:
    _freeze(monkeypatch, "2026-06-06T10:00:00+09:00")  # 土曜
    assert tasks._is_weekday_jst() is False
    assert tasks._is_market_hours_jst() is False


def test_weekday_before_market_open_is_out_of_hours(monkeypatch: pytest.MonkeyPatch) -> None:
    _freeze(monkeypatch, "2026-06-02T08:59:00+09:00")
    assert tasks._is_market_hours_jst() is False


def test_weekday_after_market_close_is_out_of_hours(monkeypatch: pytest.MonkeyPatch) -> None:
    _freeze(monkeypatch, "2026-06-02T15:31:00+09:00")
    assert tasks._is_market_hours_jst() is False


def test_market_open_and_close_boundaries_are_inclusive(monkeypatch: pytest.MonkeyPatch) -> None:
    _freeze(monkeypatch, "2026-06-02T09:00:00+09:00")
    assert tasks._is_market_hours_jst() is True
    _freeze(monkeypatch, "2026-06-02T15:30:00+09:00")
    assert tasks._is_market_hours_jst() is True


def test_run_portfolio_monitor_task_noops_outside_market_hours(monkeypatch: pytest.MonkeyPatch) -> None:
    _freeze(monkeypatch, "2026-06-06T10:00:00+09:00")  # 土曜
    assert tasks.run_portfolio_monitor_task() is None


def test_frozen_time_is_jst(monkeypatch: pytest.MonkeyPatch) -> None:
    _freeze(monkeypatch, "2026-06-02T10:00:00+09:00")
    assert tasks.datetime.now(JST).hour == 10
