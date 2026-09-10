"""JST ヘルパーの検証（Market Lens から移植したユーティリティ）."""

from __future__ import annotations

import re

import pandas as pd

from backend.services.jst_time import (
    is_today_jst,
    merge_equity_curves,
    to_jst,
    today_jst,
    week_jst,
)


def test_today_jst_is_iso_date() -> None:
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", today_jst())


def test_week_jst_is_iso_week() -> None:
    assert re.fullmatch(r"\d{4}-W\d{2}", week_jst())


def test_to_jst_localizes_naive_and_converts_aware() -> None:
    naive = pd.Timestamp("2026-09-10 09:00:00")
    localized = to_jst(naive)
    assert str(localized.tz) == "Asia/Tokyo"

    utc = pd.Timestamp("2026-09-10 00:00:00", tz="UTC")
    converted = to_jst(utc)
    assert converted.hour == 9  # UTC+9


def test_is_today_jst_true_for_now() -> None:
    assert is_today_jst(pd.Timestamp.now(tz="Asia/Tokyo")) is True
    assert is_today_jst(pd.Timestamp("2000-01-01", tz="Asia/Tokyo")) is False


def test_merge_equity_curves_aligns_and_sums() -> None:
    a = pd.Series([100.0, 110.0], index=pd.to_datetime(["2026-09-08", "2026-09-09"]))
    b = pd.Series([50.0, 55.0], index=pd.to_datetime(["2026-09-09", "2026-09-10"]))
    total = merge_equity_curves({"7203": a, "6758": b})
    # 3 タイムスタンプの和集合。2026-09-08 は b が bfill(50)、2026-09-10 は a が ffill(110)。
    assert list(total.index) == list(pd.to_datetime(["2026-09-08", "2026-09-09", "2026-09-10"]))
    assert total.loc[pd.Timestamp("2026-09-09")] == 110.0 + 50.0


def test_merge_equity_curves_empty_returns_empty_series() -> None:
    assert merge_equity_curves({}).empty
