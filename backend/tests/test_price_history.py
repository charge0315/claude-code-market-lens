"""`services/vault_report/price_history` の検証（ピック前日までの未来リーク防止）."""

from __future__ import annotations

import pandas as pd
import pytest

from backend.services.vault_report import price_history as ph


def _history(dates: list[str], closes: list[float]) -> pd.DataFrame:
    index = pd.DatetimeIndex(pd.to_datetime(dates)).tz_localize("Asia/Tokyo")
    return pd.DataFrame({"Close": closes}, index=index)


async def test_fetch_price_history_before_excludes_pick_day_and_later(monkeypatch: pytest.MonkeyPatch) -> None:
    """`before_date` 当日・以降の終値は含めない（未来リーク防止、実測: ピック当日は開始直後で未確定）."""
    hist = _history(
        ["2026-09-14", "2026-09-15", "2026-09-16", "2026-09-17", "2026-09-18"],
        [100.0, 105.0, 110.0, 999.0, 999.0],
    )
    monkeypatch.setattr(ph, "fetch_stock_data", lambda *_a, **_k: hist)

    series = await ph.fetch_price_history_before("7203", "2026-09-17")

    assert series == [("2026-09-14", 100.0), ("2026-09-15", 105.0), ("2026-09-16", 110.0)]


async def test_fetch_price_history_before_caps_at_max_points(monkeypatch: pytest.MonkeyPatch) -> None:
    dates = pd.date_range("2026-01-01", periods=100, freq="D").strftime("%Y-%m-%d").tolist()
    hist = _history(dates, [float(i) for i in range(100)])
    monkeypatch.setattr(ph, "fetch_stock_data", lambda *_a, **_k: hist)

    series = await ph.fetch_price_history_before("7203", "2026-12-31")

    assert len(series) == 60
    assert series[-1] == ("2026-04-10", 99.0)


async def test_fetch_price_history_before_returns_empty_on_fetch_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    def _raise(*_a: object, **_k: object) -> pd.DataFrame:
        raise RuntimeError("yfinance down")

    monkeypatch.setattr(ph, "fetch_stock_data", _raise)

    series = await ph.fetch_price_history_before("7203", "2026-09-17")

    assert series == []


async def test_fetch_price_history_before_returns_empty_for_empty_history(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ph, "fetch_stock_data", lambda *_a, **_k: pd.DataFrame())

    series = await ph.fetch_price_history_before("7203", "2026-09-17")

    assert series == []
