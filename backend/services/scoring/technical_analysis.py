"""テクニカル指標の計算ロジック（純粋関数群）.

Market Lens `backend/services/technical_analysis.py` から移植（変更なし）。
I/O・DB・ネットワークを持たないため、価格 DataFrame さえあれば単体テストできる。
ATR（`compute_atr` / `compute_atr_series`）は 3 値ブラケットの損切り幅算出（P3）と
決着記録のトリプルバリア（P4）で共有する。
"""

from __future__ import annotations

from typing import Literal, TypedDict

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
    """時系列データを {date, value} 辞書のリストに変換する.

    🆕 P37: 要素ごとの `series.iloc[i]` / `index[i]` は 1 回あたり数十 µs かかり、テクニカル採点
    1 銘柄で約 0.1 秒を占めていた（過去日リプレイで 950 日 × 候補数ぶん呼ぶと律速になる）。
    `to_numpy()` を反復して一括変換する（`iloc` と同じ numpy スカラーが得られるので、`np.int64` が
    `_safe_value` で None になる従来の挙動も含め出力は同一。`tolist()` だと Python int に化けて変わる）。
    """
    n = len(series)
    dates = [ts.isoformat()[:10] if hasattr(ts, "isoformat") else str(ts) for ts in index[:n]]
    return [IndicatorPoint(date=d, value=_safe_value(v)) for d, v in zip(dates, series.to_numpy(), strict=True)]


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


def calculate_stochastics(
    df: pd.DataFrame, *, k_period: int = 14, smooth_k: int = 3, d_period: int = 3
) -> dict[str, list[IndicatorPoint]]:
    """ストキャスティクス（%K/%D、スロー方式）— 一定期間の高安レンジ内での終値の位置を示す.

    %K は直近安値からの位置を 0-100 で表した生値を `smooth_k` 期間で平滑化したもの
    （TradingView 等のデファクトである「スロー」方式）、%D はさらに `%K` を `d_period`
    期間で平滑化したシグナル線。
    """
    high = df["High"].rolling(window=k_period).max()
    low = df["Low"].rolling(window=k_period).min()
    raw_k = (df["Close"] - low) / (high - low).replace(0, np.nan) * 100.0
    slow_k = raw_k.rolling(window=smooth_k).mean()
    slow_d = slow_k.rolling(window=d_period).mean()
    return {
        "%K": _series_to_records(slow_k, df.index),
        "%D": _series_to_records(slow_d, df.index),
    }


def _future_business_dates(index: pd.DatetimeIndex | pd.Index, periods: int) -> list[str]:
    """一目均衡表の先行スパン用に、`index` の最終日から `periods` 本分の未来営業日を返す.

    平日カレンダーで近似する（JST祝日は考慮しない — 雲はチャートの視覚的な先行表示であり
    実売買判定には使わないため、厳密な東証営業日暦までは要求しない。ローソク足自体の
    休場日判定は `_is_trading_day_jst` 側で別途担保している）。
    """
    shifted = pd.bdate_range(start=index[-1], periods=periods + 1)[1:]
    return [ts.isoformat()[:10] for ts in shifted]


def _forward_shift_records(
    series: pd.Series, index: pd.DatetimeIndex | pd.Index, future_dates: list[str], periods: int
) -> list[IndicatorPoint]:
    """`series`（`index` と同じ長さ）を `periods` 本分だけ未来へ前進させた記録列を返す.

    一目均衡表の先行スパンは「時点 i で計算した値を時点 i+periods の位置に表示する」ため、
    出力の先頭 `periods` 本は過去に値が無く常に None、末尾は元の系列に無い未来日付
    （`future_dates`）へ最終 `periods` 本の値を割り当てる形になる。
    """
    values = series.to_numpy()
    n = len(values)
    shifted_past = [
        IndicatorPoint(date=_to_date_str(index, i), value=_safe_value(values[i - periods]) if i >= periods else None)
        for i in range(n)
    ]
    future_values = values[max(n - periods, 0) :]
    future = [IndicatorPoint(date=d, value=_safe_value(v)) for d, v in zip(future_dates, future_values, strict=False)]
    return shifted_past + future


def calculate_ichimoku(
    df: pd.DataFrame, *, tenkan: int = 9, kijun: int = 26, senkou_b: int = 52
) -> dict[str, list[IndicatorPoint]]:
    """一目均衡表 — 転換線/基準線/先行スパンA・B（雲）/遅行スパンの5本（🆕 日足専用）.

    先行スパンA・Bは計算時点から `kijun` 本先の位置へ前進表示するのが一般的な描画方式
    のため、元のインデックスに無い将来日付（近似カレンダー、`_future_business_dates`
    参照）を追加で生成する（`_forward_shift_records`）。遅行スパンは逆に `kijun` 本分
    過去へ表示するだけなので、既存のインデックス内に収まり追加生成は不要
    （`pd.Series.shift(-kijun)` で足りる）。分足は日足前提の日付文字列キーが同日内で
    衝突するため対象外（`routers/stock.py` 参照、GC/DC・MACDクロスと同じ理由）。
    """
    high, low, close = df["High"], df["Low"], df["Close"]

    tenkan_sen = (high.rolling(tenkan).max() + low.rolling(tenkan).min()) / 2
    kijun_sen = (high.rolling(kijun).max() + low.rolling(kijun).min()) / 2
    senkou_a = (tenkan_sen + kijun_sen) / 2
    senkou_b_line = (high.rolling(senkou_b).max() + low.rolling(senkou_b).min()) / 2
    chikou = close.shift(-kijun)

    future_dates = _future_business_dates(df.index, kijun)

    return {
        "転換線": _series_to_records(tenkan_sen, df.index),
        "基準線": _series_to_records(kijun_sen, df.index),
        "先行スパンA": _forward_shift_records(senkou_a, df.index, future_dates, kijun),
        "先行スパンB": _forward_shift_records(senkou_b_line, df.index, future_dates, kijun),
        "遅行スパン": _series_to_records(chikou, df.index),
    }


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


class CrossEvent(TypedDict):
    """テクニカル指標のクロス（イベント発生日）— チャートのゴールデンクロス/デッドクロス等の
    マーカー用（🆕）。`IndicatorPoint` が「ある時点の値」の状態しか持たないのに対し、こちらは
    「その日に交差というイベントが発生したこと」を表す。
    """

    date: str
    kind: Literal["golden_cross", "dead_cross", "macd_bullish_cross", "macd_bearish_cross"]
    label: str


def _detect_two_line_cross(
    short: list[IndicatorPoint],
    long: list[IndicatorPoint],
    *,
    bullish_kind: Literal["golden_cross", "macd_bullish_cross"],
    bearish_kind: Literal["dead_cross", "macd_bearish_cross"],
    bullish_label: str,
    bearish_label: str,
) -> list[CrossEvent]:
    """同じ日付軸を持つ 2 本の指標系列が交差した日を検出する共通ロジック.

    前日→当日で (short - long) の符号が 0以下→正 に転じた日を強気クロス、
    正以上→負 に転じた日を弱気クロスとする。どちらかが None（指標の計算窓に満たない）
    区間は交差判定の対象外にする。

    先頭2点（index 0, 1）は比較の起点にしない: MACD のシグナル線は EMA の初項が
    MACD 線の先頭値そのものであるため、index 0 では常に diff=0 になり、index 1 との
    比較で「疑似クロス」が発生してしまう（直前の履歴が無い系列先頭を交差と呼ぶのは
    そもそも無意味）。SMA 側は先頭が None のため元々スキップされ影響しない。
    """
    events: list[CrossEvent] = []
    for i in range(2, len(short)):
        prev_s, prev_l = short[i - 1]["value"], long[i - 1]["value"]
        cur_s, cur_l = short[i]["value"], long[i]["value"]
        if prev_s is None or prev_l is None or cur_s is None or cur_l is None:
            continue
        prev_diff = prev_s - prev_l
        cur_diff = cur_s - cur_l
        if prev_diff <= 0 < cur_diff:
            events.append(CrossEvent(date=short[i]["date"], kind=bullish_kind, label=bullish_label))
        elif prev_diff >= 0 > cur_diff:
            events.append(CrossEvent(date=short[i]["date"], kind=bearish_kind, label=bearish_label))
    return events


def detect_sma_cross_events(df: pd.DataFrame, *, short: int = 5, long: int = 25) -> list[CrossEvent]:
    """SMA短期線（既定5日）が中期線（既定25日）を上抜け/下抜けした日を検出する（ゴールデンクロス/デッドクロス）."""
    sma = calculate_sma(df, [short, long])
    return _detect_two_line_cross(
        sma[f"SMA_{short}"],
        sma[f"SMA_{long}"],
        bullish_kind="golden_cross",
        bearish_kind="dead_cross",
        bullish_label=f"ゴールデンクロス（短期線がSMA{long}を下から上へ突破。上昇トレンド転換の兆候です。）",
        bearish_label=f"デッドクロス（短期線がSMA{long}を上から下へ突破。下降トレンド転換の兆候です。）",
    )


def detect_macd_cross_events(df: pd.DataFrame) -> list[CrossEvent]:
    """MACD線がシグナル線を上抜け/下抜けした日を検出する."""
    macd = calculate_macd(df)
    return _detect_two_line_cross(
        macd["MACD"],
        macd["Signal"],
        bullish_kind="macd_bullish_cross",
        bearish_kind="macd_bearish_cross",
        bullish_label="MACDゴールデンクロス（MACD線がシグナル線を上抜け。上昇モメンタムの兆候です。）",
        bearish_label="MACDデッドクロス（MACD線がシグナル線を下抜け。下降モメンタムの兆候です。）",
    )


def detect_cross_events(df: pd.DataFrame) -> list[CrossEvent]:
    """SMA・MACDのクロスイベントを日付昇順にマージして返す（チャートAPI用の統合エントリ）."""
    events = detect_sma_cross_events(df) + detect_macd_cross_events(df)
    return sorted(events, key=lambda e: e["date"])
