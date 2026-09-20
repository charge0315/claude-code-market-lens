"""営業日カレンダーユーティリティの検証."""

from __future__ import annotations

from datetime import datetime as real_datetime

import pandas as pd
import pytest

from backend.services import trading_calendar as tc
from backend.services.trading_calendar import (
    calc_target_date,
    is_market_hours_jst,
    is_trading_day_jst,
    is_weekday_jst,
    market_status_label,
)


def test_calc_target_date_skips_weekend() -> None:
    # 2026-09-11 は金曜。1 営業日先は翌月曜 2026-09-14。
    assert calc_target_date(pd.Timestamp("2026-09-11"), 1) == "2026-09-14"


def test_calc_target_date_multiple_business_days() -> None:
    assert calc_target_date(pd.Timestamp("2026-09-10"), 5) == "2026-09-17"


@pytest.mark.parametrize("horizon", [0, -1])
def test_calc_target_date_rejects_non_positive_horizon(horizon: int) -> None:
    with pytest.raises(ValueError, match="horizon"):
        calc_target_date(pd.Timestamp("2026-09-10"), horizon)


class _FrozenDatetime(real_datetime):
    _frozen: real_datetime

    @classmethod
    def now(cls, tz: object = None) -> real_datetime:  # type: ignore[override]  # noqa: ARG003
        return cls._frozen


def _freeze(monkeypatch: pytest.MonkeyPatch, iso: str) -> None:
    frozen = real_datetime.fromisoformat(iso)
    fake = type("_Frozen", (_FrozenDatetime,), {"_frozen": frozen})
    monkeypatch.setattr(tc, "datetime", fake)


def test_weekday_during_market_hours(monkeypatch: pytest.MonkeyPatch) -> None:
    _freeze(monkeypatch, "2026-06-02T10:00:00+09:00")  # 火曜
    assert is_weekday_jst() is True
    assert is_market_hours_jst() is True
    assert market_status_label() == "ザラ場中"


def test_weekend_is_not_weekday(monkeypatch: pytest.MonkeyPatch) -> None:
    _freeze(monkeypatch, "2026-06-06T10:00:00+09:00")  # 土曜
    assert is_weekday_jst() is False
    assert is_market_hours_jst() is False
    assert market_status_label() == "引け後"


def test_before_market_open_label(monkeypatch: pytest.MonkeyPatch) -> None:
    _freeze(monkeypatch, "2026-06-02T08:59:00+09:00")
    assert is_market_hours_jst() is False
    assert market_status_label() == "寄り前"


def test_after_market_close_label(monkeypatch: pytest.MonkeyPatch) -> None:
    _freeze(monkeypatch, "2026-06-02T15:31:00+09:00")
    assert is_market_hours_jst() is False
    assert market_status_label() == "引け後"


def test_market_open_and_close_boundaries_are_inclusive(monkeypatch: pytest.MonkeyPatch) -> None:
    _freeze(monkeypatch, "2026-06-02T09:00:00+09:00")
    assert is_market_hours_jst() is True
    _freeze(monkeypatch, "2026-06-02T15:30:00+09:00")
    assert is_market_hours_jst() is True


@pytest.mark.parametrize(
    "iso",
    [
        "2026-09-21T10:00:00+09:00",  # 月曜・敬老の日
        "2026-09-22T10:00:00+09:00",  # 火曜・国民の休日（敬老の日と秋分の日に挟まれる）
        "2026-09-23T10:00:00+09:00",  # 水曜・秋分の日
    ],
)
def test_national_holiday_is_weekday_but_not_trading_day(monkeypatch: pytest.MonkeyPatch, iso: str) -> None:
    """曜日だけでは検出できない祝日（2026-09-21〜23の3連休）を `is_trading_day_jst` で除外する."""
    _freeze(monkeypatch, iso)
    assert is_weekday_jst() is True  # 曜日だけなら平日
    assert is_trading_day_jst() is False
    assert is_market_hours_jst() is False
    assert market_status_label() == "引け後"
