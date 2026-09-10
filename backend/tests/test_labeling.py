"""トリプルバリア走査プリミティブの検証（Market Lens から移植）."""

from __future__ import annotations

import math

from backend.services.ledger.labeling import first_barrier_touch


def test_take_profit_hit_first() -> None:
    highs = [101, 103, 106]
    lows = [99, 100, 104]
    assert first_barrier_touch(highs, lows, stop_loss=95, take_profit=105) == (2, "take_profit")


def test_stop_loss_hit_first() -> None:
    highs = [101, 102, 103]
    lows = [99, 94, 100]
    assert first_barrier_touch(highs, lows, stop_loss=95, take_profit=110) == (1, "stop_loss")


def test_same_day_both_touched_prefers_stop_loss() -> None:
    highs = [111]
    lows = [94]
    assert first_barrier_touch(highs, lows, stop_loss=95, take_profit=110) == (0, "stop_loss")


def test_no_touch_returns_none() -> None:
    highs = [101, 102, 103]
    lows = [99, 98, 100]
    assert first_barrier_touch(highs, lows, stop_loss=90, take_profit=110) is None


def test_nan_bar_is_skipped() -> None:
    highs = [math.nan, 111]
    lows = [math.nan, 100]
    assert first_barrier_touch(highs, lows, stop_loss=95, take_profit=110) == (1, "take_profit")
