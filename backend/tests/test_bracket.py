"""3 値ブラケットの算出・クランプ・サーバ側検証の検証（Market Lens から移植）."""

from __future__ import annotations

import pytest

from backend.services.picks.bracket import (
    Bracket,
    clamp_bracket,
    finalize_bracket,
    standardize_holding_period,
    suggested_bracket,
    validate_bracket,
)


def test_validate_bracket_accepts_consistent_three_values() -> None:
    assert validate_bracket(current_price=1000, entry=1005, stop=950, target=1100) is None


@pytest.mark.parametrize(
    ("entry", "stop", "target", "fragment"),
    [
        (1005, 1000, 1100, "現在値以上"),  # stop >= price
        (1005, 950, 1000, "現在値以下"),  # target <= price
        (1200, 950, 1100, "レンジの外"),  # entry > target
        (900, 950, 1100, "レンジの外"),  # entry < stop
        (-1, 950, 1100, "非正の価格"),
    ],
)
def test_validate_bracket_rejects_inconsistent(entry: float, stop: float, target: float, fragment: str) -> None:
    reason = validate_bracket(current_price=1000, entry=entry, stop=stop, target=target)
    assert reason is not None and fragment in reason


def test_clamp_bracket_pulls_values_into_atr_bands_and_keeps_ordering() -> None:
    price, atr = 1000.0, 20.0
    # 損切り遠すぎ (900 = 5*ATR 下)・利確遠すぎ (1200 = 10*ATR 上)・買値低すぎ (960)。
    b = clamp_bracket(price, atr, entry=960, stop=900, target=1200)
    assert b.stop == pytest.approx(price - 3.0 * atr)  # _SL_ATR_MAX
    assert b.target == pytest.approx(price + 4.0 * atr)  # _TP_ATR_MAX
    assert b.stop < b.entry < b.target
    assert b.entry >= price - 0.1 * atr  # _BUY_ATR_BELOW


def test_finalize_bracket_rejects_then_clamps() -> None:
    b, reason = finalize_bracket(1000, 20.0, raw_entry=1005, raw_stop=1000, raw_target=1100)
    assert b is None and reason is not None  # stop >= price → 却下

    b, reason = finalize_bracket(1000, 20.0, raw_entry=1002, raw_stop=985, raw_target=1050)
    assert reason is None and b is not None
    assert b.stop < b.entry < b.target


def test_finalize_bracket_without_atr_passes_llm_values_through() -> None:
    b, reason = finalize_bracket(1000, None, raw_entry=1002, raw_stop=985, raw_target=1050)
    assert reason is None
    assert b == Bracket(entry=1002, stop=985, target=1050)


def test_suggested_bracket_shape() -> None:
    s = suggested_bracket(1000, 20.0)
    assert s["entry"] == 1000.0
    assert s["stop"] == 1000 - 1.5 * 20
    assert s["target"] == 1000 + 2.5 * 20
    assert "ATR" in str(s["note"])


@pytest.mark.parametrize(("raw", "expected"), [(3, 5), (7, 7), (30, 10), ("x", 7), (None, 7)])
def test_standardize_holding_period(raw: object, expected: int) -> None:
    assert standardize_holding_period(raw) == expected
