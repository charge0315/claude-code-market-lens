"""テクニカル指標（純粋関数）の検証（Market Lens から移植）."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from backend.services.scoring import technical_analysis as ta


@pytest.fixture
def price_df() -> pd.DataFrame:
    idx = pd.date_range("2026-01-01", periods=60, freq="B")
    close = pd.Series(np.linspace(100, 130, 60), index=idx)
    return pd.DataFrame(
        {
            "Open": close.shift(1).fillna(close.iloc[0]),
            "High": close + 1.5,
            "Low": close - 1.5,
            "Close": close,
            "Volume": pd.Series(np.full(60, 1_000_000), index=idx),
        }
    )


def test_sma_and_ema_have_one_record_per_row(price_df: pd.DataFrame) -> None:
    sma = ta.calculate_sma(price_df, [5, 25])
    assert set(sma) == {"SMA_5", "SMA_25"}
    assert len(sma["SMA_5"]) == len(price_df)
    # 先頭 4 行は窓が埋まらず None。
    assert sma["SMA_5"][0]["value"] is None
    assert sma["SMA_5"][-1]["value"] is not None

    ema = ta.calculate_ema(price_df, [12])
    assert len(ema["EMA_12"]) == len(price_df)


def test_rsi_of_monotonic_uptrend_is_high(price_df: pd.DataFrame) -> None:
    rsi = ta.calculate_rsi(price_df, period=14)
    last = rsi[-1]["value"]
    assert last is not None and last > 90  # 一本調子の上昇 → RSI は 100 近く


def test_macd_returns_three_series(price_df: pd.DataFrame) -> None:
    macd = ta.calculate_macd(price_df)
    assert set(macd) == {"MACD", "Signal", "Histogram"}


def test_bollinger_bands_upper_above_lower(price_df: pd.DataFrame) -> None:
    bb = ta.calculate_bollinger_bands(price_df, period=20)
    upper = bb["Upper"][-1]["value"]
    lower = bb["Lower"][-1]["value"]
    assert upper is not None and lower is not None and upper > lower


def test_compute_atr_positive_and_none_on_short_frame(price_df: pd.DataFrame) -> None:
    atr = ta.compute_atr(price_df, period=14)
    assert atr is not None and atr > 0
    assert ta.compute_atr(price_df.head(3), period=14) is None


def test_compute_atr_series_matches_scalar_tail(price_df: pd.DataFrame) -> None:
    series = ta.compute_atr_series(price_df, period=14)
    assert series.iloc[-1] == pytest.approx(ta.compute_atr(price_df, period=14))
