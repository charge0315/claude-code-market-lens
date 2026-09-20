"""`tasks._is_weekday_jst` / `_is_market_hours_jst`（保有監視 beat のゲート判定）の検証."""

from __future__ import annotations

from datetime import datetime as real_datetime
from pathlib import Path

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


@pytest.mark.parametrize(
    "iso",
    [
        "2026-09-21T10:00:00+09:00",  # 月曜・敬老の日
        "2026-09-22T10:00:00+09:00",  # 火曜・国民の休日（敬老の日と秋分の日に挟まれる）
        "2026-09-23T10:00:00+09:00",  # 水曜・秋分の日
    ],
)
def test_national_holiday_is_weekday_but_not_trading_day(monkeypatch: pytest.MonkeyPatch, iso: str) -> None:
    """曜日だけでは検出できない祝日（2026-09-21〜23の3連休）を `_is_trading_day_jst` で除外する.

    `_is_weekday_jst` だけに頼っていた `run_picks_task` が、この3連休で誤発火することが
    2026-09-20（前日の日曜誤発火インシデント）判明時に発覚した。
    """
    _freeze(monkeypatch, iso)
    assert tasks._is_weekday_jst() is True  # 曜日だけなら平日
    assert tasks._is_trading_day_jst() is False
    assert tasks._is_market_hours_jst() is False


def test_run_portfolio_monitor_task_noops_outside_market_hours(monkeypatch: pytest.MonkeyPatch) -> None:
    _freeze(monkeypatch, "2026-06-06T10:00:00+09:00")  # 土曜
    assert tasks.run_portfolio_monitor_task() is None


def test_frozen_time_is_jst(monkeypatch: pytest.MonkeyPatch) -> None:
    _freeze(monkeypatch, "2026-06-02T10:00:00+09:00")
    assert tasks.datetime.now(JST).hour == 10


def test_run_eod_review_task_generates_review_regardless_of_weekday(migrated_db: Path) -> None:
    result = tasks.run_eod_review_task()

    assert result["review_date"] is not None
    assert result["heuristics"] == 0
