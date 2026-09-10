"""テクニカル指標の計算ロジック（純粋関数群）.

Market Lens `backend/services/technical_analysis.py` から移植（変更なし）。
I/O・DB・ネットワークを持たないため、価格 DataFrame さえあれば単体テストできる。
ATR（`compute_atr` / `compute_atr_series`）は 3 値ブラケットの損切り幅算出（P3）と
決着記録のトリプルバリア（P4）で共有する。
"""

from __future__ import annotations

from typing import TypedDict

import numpy as np
import pandas as pd


class IndicatorPoint(TypedDict):
    """テクニカル指標の 1 時点分のレコード（{date, value}）."""

    date: str
    value: float | None


def _to_date_str(index: pd.DatetimeIndex | pd.Index, pos: int) -> str:
    """pandas のインデックスを ISO 形式の日付文字列に変換する."""
    timestamp = index[pos]
    if hasattr(timestamp, "isoformat"):
        return timestamp.isoformat()[:10]
    return str(timestamp)


def _safe_value(val: object) -> float | None:
    """NaN / Inf 値を None に変換して JSON 安全にする."""
    if not isinstance(val, (int, float)):
        return None
    try:
        if np.isnan(val) or np.isinf(val):
            return None
    except (TypeError, ValueError):
        return None
    return float(val)


def _series_to_records(series: pd.Series, index: pd.DatetimeIndex | pd.Index) -> list[IndicatorPoint]:
    """時系列データを {date, value} 辞書のリストに変換する."""
    return [IndicatorPoint(date=_to_date_str(index, i), value=_safe_value(series.iloc[i])) for i in range(len(series))]


def calculate_sma(df: pd.DataFrame, periods: list[int]) -> dict[str, list[IndicatorPoint]]:
    """単純移動平均 — 各期間のトレンド方向を可視化する基本指標."""
    close: pd.Series = df["Close"]
    result: dict[str, list[IndicatorPoint]] = {}
    for period in periods:
        result[f"SMA_{period}"] = _series_to_records(close.rolling(window=period).mean(), df.index)
    return result


def calculate_ema(df: pd.DataFrame, periods: list[int]) -> dict[str, list[IndicatorPoint]]:
    """指数移動平均 — 直近の値動きにより敏感な加重移動平均."""
    close: pd.Series = df["Close"]
    result: dict[str, list[IndicatorPoint]] = {}
    for period in periods:
        result[f"EMA_{period}"] = _series_to_records(close.ewm(span=period, adjust=False).mean(), df.index)
    return result


def calculate_rsi(df: pd.DataFrame, period: int = 14) -> list[IndicatorPoint]:
    """RSI（相対力指数）— Wilder's 方式（TradingView 準拠・0-100）."""
    close: pd.Series = df["Close"]
    delta = close.diff()

    gains = delta.where(delta > 0, 0.0)
    losses = (-delta).where(delta < 0, 0.0)

    avg_gain = gains.ewm(alpha=1.0 / period, min_periods=period, adjust=False).mean()
    avg_loss = losses.ewm(alpha=1.0 / period, min_periods=period, adjust=False).mean()

    rs = avg_gain / avg_loss.replace(0, np.nan)
    rsi = 100.0 - (100.0 / (1.0 + rs))

    rsi.loc[avg_loss == 0] = 100.0
    rsi.loc[(avg_loss == 0) & (avg_gain == 0)] = 50.0

    return _series_to_records(rsi, df.index)


def calculate_macd(
    df: pd.DataFrame, fast: int = 12, slow: int = 26, signal: int = 9
) -> dict[str, list[IndicatorPoint]]:
    """MACD — 2 本の EMA 乖離からトレンド転換シグナルを検出する."""
    close: pd.Series = df["Close"]

    ema_fast = close.ewm(span=fast, adjust=False).mean()
    ema_slow = close.ewm(span=slow, adjust=False).mean()
    macd_line = ema_fast - ema_slow
    signal_line = macd_line.ewm(span=signal, adjust=False).mean()
    histogram = macd_line - signal_line

    return {
        "MACD": _series_to_records(macd_line, df.index),
        "Signal": _series_to_records(signal_line, df.index),
        "Histogram": _series_to_records(histogram, df.index),
    }


def calculate_bollinger_bands(
    df: pd.DataFrame, period: int = 20, std_dev: float = 2.0
) -> dict[str, list[IndicatorPoint]]:
    """ボリンジャーバンド — 価格の統計的な変動範囲を可視化する."""
    close: pd.Series = df["Close"]

    middle = close.rolling(window=period).mean()
    rolling_std = close.rolling(window=period).std()
    upper = middle + (rolling_std * std_dev)
    lower = middle - (rolling_std * std_dev)

    return {
        "Upper": _series_to_records(upper, df.index),
        "Middle": _series_to_records(middle, df.index),
        "Lower": _series_to_records(lower, df.index),
    }


def calculate_volume_analysis(df: pd.DataFrame, period: int = 20) -> list[IndicatorPoint]:
    """出来高移動平均 — 売買の活発度の推移を把握する."""
    return _series_to_records(df["Volume"].rolling(window=period).mean(), df.index)


def compute_atr_series(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """True Range の Wilder 方式平滑化平均（ATR）を系列で返す（先頭 period 行は NaN）."""
    high = df["High"]
    low = df["Low"]
    prev_close = df["Close"].shift(1)
    true_range = pd.concat([high - low, (high - prev_close).abs(), (low - prev_close).abs()], axis=1).max(axis=1)
    return true_range.ewm(alpha=1.0 / period, min_periods=period, adjust=False).mean()


def compute_atr(df: pd.DataFrame, period: int = 14) -> float | None:
    """ATR の末尾値を返す（データ不足時は None）。損切りライン設定・ボラティリティ計算に共有する."""
    if df.empty or len(df) < period + 1 or "High" not in df.columns or "Low" not in df.columns:
        return None
    last = compute_atr_series(df, period).iloc[-1]
    return float(last) if pd.notna(last) else None
