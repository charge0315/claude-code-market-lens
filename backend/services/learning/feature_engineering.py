"""断面プール型モデル（P5d）向けの per-ticker 特徴量エンジニアリング.

Market Lens `backend/services/feature_engineering.py` から移植、変更点:
`build_feature_matrix` の回帰パスのみを移植した。Market Lens には `objective="classification"`
（トリプルバリア2値ラベル、LSTM 用）と `feature_version` の 1/2 バイト互換フラグがあるが、
Alpha Forge にはまだ学習済みモデルが存在せず後方互換を保つ理由がないため削除し、Market Lens の
v2 相当（macd 系を Close で無次元化、day_of_week/month を周期エンコーディング）を既定かつ唯一の
挙動にした。`build_sequence_matrix`（LSTM 用）は per-ticker ローテーションと共に対象外（P5d は
断面プールモデルのみを移植する方針、`plans/04_タスクリスト.md` P5d 参照）。
"""

from __future__ import annotations

import numpy as np
import pandas as pd

_MIN_HISTORY_DAYS = 50


def build_feature_matrix(
    df: pd.DataFrame,
    target_col: str = "Close",
    forecast_horizon: int = 5,
    predict_mode: bool = False,
) -> tuple[pd.DataFrame, pd.Series | None]:
    """OHLCV データフレームから特徴量行列(X)とターゲット変数(y)を生成する.

    Args:
        df: 日付をインデックスに持つ OHLCV データフレーム
        target_col: 予測対象の列名（デフォルト: Close）
        forecast_horizon: 何日先を予測するか（デフォルト: 5日）
        predict_mode: True の場合、ターゲット変数を生成せず特徴量のみを返す（NaN 除去は
            特徴量列のみで行うため、直近日（未来の実現リターンが無い行）も残る）。
            断面プール推論（`panel_feature_service.build_panel_context`）はこちらを使う
            （🔧 Market Lens は既定 False のまま呼んでいたため、直近 forecast_horizon 日分が
            ターゲット起因の dropna で失われ本番当日の推論行が欠落し得た。学習パネルは
            ラベルを `pool_labeling.cross_sectional_label` から得るため本関数の y を使わず、
            この関数の predict_mode=True 化は学習・推論の両方で安全）

    Returns:
        X (pd.DataFrame): 特徴量行列
        y (pd.Series | None): ターゲット変数（predict_mode=True の時は None）
    """
    if len(df) < _MIN_HISTORY_DAYS:
        raise ValueError(f"データが少なすぎます（最低{_MIN_HISTORY_DAYS}日分必要）")

    data = df.copy()
    features = pd.DataFrame(index=data.index)

    # 1. ラグ特徴量（過去1〜5日の価格と出来高の変化率）
    for lag in range(1, 6):
        features[f"return_lag_{lag}"] = data["Close"].pct_change(periods=lag)
        features[f"volume_lag_{lag}"] = data["Volume"].pct_change(periods=lag)

    # 2. テクニカル指標特徴量
    for period in [5, 20, 50]:
        sma = data["Close"].rolling(window=period).mean()
        features[f"sma_{period}_diff"] = (data["Close"] - sma) / sma

    ema_12 = data["Close"].ewm(span=12, adjust=False).mean()
    ema_26 = data["Close"].ewm(span=26, adjust=False).mean()
    features["ema_12_diff"] = (data["Close"] - ema_12) / ema_12

    macd = ema_12 - ema_26
    signal = macd.ewm(span=9, adjust=False).mean()
    # 円の絶対水準（銘柄の株価水準に依存しスケールが暴れる）のままでは銘柄横断の学習で
    # 意味を持たないため、Close で除して無次元化する。
    features["macd"] = macd / data["Close"]
    features["macd_signal"] = signal / data["Close"]
    features["macd_hist"] = (macd - signal) / data["Close"]

    sma_20 = data["Close"].rolling(window=20).mean()
    std_20 = data["Close"].rolling(window=20).std()
    upper_band = sma_20 + (std_20 * 2)
    lower_band = sma_20 - (std_20 * 2)
    features["bb_width"] = (upper_band - lower_band) / sma_20
    bb_range = (upper_band - lower_band).replace(0, np.nan)
    features["bb_position"] = (data["Close"] - lower_band) / bb_range

    delta = data["Close"].diff()
    gain = delta.where(delta > 0, 0.0)
    loss = (-delta).where(delta < 0, 0.0)
    avg_gain = gain.ewm(alpha=1.0 / 14, min_periods=14, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1.0 / 14, min_periods=14, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    rsi = 100.0 - (100.0 / (1.0 + rs))
    is_zero_loss = avg_loss == 0
    is_zero_gain = avg_gain == 0
    rsi.loc[is_zero_loss] = 100.0
    rsi.loc[is_zero_loss & is_zero_gain] = 50.0
    features["rsi_14"] = rsi

    features["volatility_5"] = data["Close"].pct_change().rolling(5).std()
    features["volatility_20"] = data["Close"].pct_change().rolling(20).std()

    # 3. 日付カテゴリカル特徴量（周期エンコーディング）。生整数だと「月曜(0)と日曜(6)は
    # 隣接している」という周期性をモデルが学習できないため sin/cos ペアで円周上に表現する。
    if isinstance(features.index, pd.DatetimeIndex):
        day_of_week = features.index.dayofweek
        month = features.index.month
    else:
        day_of_week = np.zeros(len(features), dtype=int)
        month = np.ones(len(features), dtype=int)
    features["day_of_week_sin"] = np.sin(2 * np.pi * day_of_week / 7)
    features["day_of_week_cos"] = np.cos(2 * np.pi * day_of_week / 7)
    features["month_sin"] = np.sin(2 * np.pi * month / 12)
    features["month_cos"] = np.cos(2 * np.pi * month / 12)

    if predict_mode:
        features = features.replace([np.inf, -np.inf], np.nan).dropna()
        if len(features) == 0:
            raise ValueError("特徴量生成後に有効なデータが0件になりました。")
        return features, None

    # 4. ターゲット変数の生成
    y = data[target_col].pct_change(periods=forecast_horizon).shift(-forecast_horizon)

    # 5. 無効値の除去
    combined = features.copy()
    combined["_target"] = y
    combined = combined.replace([np.inf, -np.inf], np.nan)
    combined = combined.dropna()

    if len(combined) == 0:
        raise ValueError("特徴量生成後に有効なデータが0件になりました。")

    X = combined.drop(columns=["_target"])
    Y = combined["_target"]

    return X, Y
