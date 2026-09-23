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


def test_stochastics_of_monotonic_uptrend_is_high(price_df: pd.DataFrame) -> None:
    stoch = ta.calculate_stochastics(price_df, k_period=14, smooth_k=3, d_period=3)
    assert set(stoch) == {"%K", "%D"}
    k_last = stoch["%K"][-1]["value"]
    # 一本調子の上昇 → 直近終値は期間内高値付近 → %K はスロー平滑化後も買われすぎ水準（80超）。
    assert k_last is not None and k_last > 80


def test_ichimoku_returns_five_lines_with_forward_shifted_cloud(price_df: pd.DataFrame) -> None:
    ichimoku = ta.calculate_ichimoku(price_df, tenkan=9, kijun=26, senkou_b=52)
    assert set(ichimoku) == {"転換線", "基準線", "先行スパンA", "先行スパンB", "遅行スパン"}

    # 転換線・基準線・遅行スパンは元の本数のまま（前進表示しない）。
    assert len(ichimoku["転換線"]) == len(price_df)
    assert len(ichimoku["遅行スパン"]) == len(price_df)

    # 先行スパンA/Bは26本先まで前進表示するため、元の本数+26本になる。
    assert len(ichimoku["先行スパンA"]) == len(price_df) + 26
    assert len(ichimoku["先行スパンB"]) == len(price_df) + 26

    # 前進表示の先頭26本は「まだ何も前進してきていない」ため必ず値が無い。
    assert all(p["value"] is None for p in ichimoku["先行スパンA"][:26])
    # 末尾（未来日付側）は元データの終盤の値が前進してきているので値がある。
    assert ichimoku["先行スパンA"][-1]["value"] is not None
    # 未来日付は元データの最終日より後であること。
    assert ichimoku["先行スパンA"][-1]["date"] > price_df.index[-1].isoformat()[:10]


def test_compute_atr_series_matches_scalar_tail(price_df: pd.DataFrame) -> None:
    series = ta.compute_atr_series(price_df, period=14)
    assert series.iloc[-1] == pytest.approx(ta.compute_atr(price_df, period=14))


def test_series_to_records_matches_elementwise_reference() -> None:
    """🆕 P37: 高速化（要素ごとの iloc → 一括変換）で出力が変わらないことの特性テスト."""
    import numpy as np
    import pandas as pd

    from backend.services.scoring.technical_analysis import _safe_value, _series_to_records, _to_date_str

    idx = pd.date_range("2024-01-01", periods=50, freq="B")
    values = np.random.default_rng(0).normal(size=50)
    values[[0, 3, 7]] = np.nan
    values[10] = np.inf
    series = pd.Series(values, index=idx)
    int_series = pd.Series(range(50), index=idx)

    for s in (series, int_series):
        expected = [{"date": _to_date_str(idx, i), "value": _safe_value(s.iloc[i])} for i in range(len(s))]
        assert _series_to_records(s, idx) == expected
