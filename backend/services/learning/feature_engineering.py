"""断面プールモデル（P5d）・銘柄別モデル（P9）向けの特徴量エンジニアリング.

Market Lens `backend/services/feature_engineering.py` から移植、変更点:
`build_feature_matrix`（断面プール用、行 = 1 銘柄 1 営業日）・`build_sequence_matrix`
（銘柄別 LSTM/Transformer 用、行 = 1 銘柄の時系列ウィンドウ）ともに回帰パスのみを移植した。
Market Lens には `objective="classification"`（トリプルバリア2値ラベル）と `feature_version`
の 1/2 バイト互換フラグ、`macro_df`（マクロ指標 opt-in）があるが、Alpha Forge にはまだ
学習済みモデルが存在せず後方互換を保つ理由がないため削除し、Market Lens の v2 相当（macd 系を
Close で無次元化、day_of_week/month を周期エンコーディング）を既定かつ唯一の挙動にした。
"""

from __future__ import annotations

import numpy as np
import pandas as pd

# 🔧 P14: 学習データの十分性判定に他モジュール（training_data_source.py の J-Quants
# フォールバック判定）から再利用するため公開する。
MIN_HISTORY_DAYS = 50


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
    if len(df) < MIN_HISTORY_DAYS:
        raise ValueError(f"データが少なすぎます（最低{MIN_HISTORY_DAYS}日分必要）")

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


def build_sequence_matrix(
    df: pd.DataFrame,
    seq_len: int = 30,
    forecast_horizon: int = 5,
    predict_mode: bool = False,
) -> tuple[np.ndarray, np.ndarray | None, pd.Index]:
    """OHLCV データから LSTM/Transformer 用の3Dシーケンスデータを生成する（銘柄別モデル、P9）.

    `build_feature_matrix` とは特徴量の作り方（1 銘柄の時系列ウィンドウ vs 銘柄横断の1行）が
    異なるため独立した関数として持つ。列構成もこちらは close_return/volume_return 等の
    無次元量のみ（sin/cos の日付特徴量は持たない — シーケンス内の相対位置で十分なため）。

    `predict_mode=True` は `build_feature_matrix` と同じ理由でターゲットを一切計算せず
    特徴量列のみで dropna する（🔧 Market Lens はターゲット計算後に dropna していたため、
    直近 forecast_horizon 日分が「ターゲットが未来を参照できない」という理由だけで失われ、
    本番当日の推論に使うべき最新シーケンスが欠落し得た）。

    Args:
        df: 日付をインデックスに持つ OHLCV データフレーム（1 銘柄分）
        seq_len: 1 サンプルあたりの入力タイムステップ数
        forecast_horizon: 何日先の変化率を予測するか
        predict_mode: True の場合は最新シーケンスのみ返し、y は None を返す

    Returns:
        X: shape (n_samples, seq_len, n_features) の ndarray
        y: shape (n_samples,) の ndarray（predict_mode=True なら None）
        dates: 各サンプルのターゲット日付（y[i] が対象とする日）を持つ Index。
            predict_mode=True の場合は「推論に使った最新1行の日付」を長さ1で返す。
            品質ゲートで新旧モデルの検証窓を揃えるために使う。
    """
    if len(df) < seq_len + forecast_horizon + 1:
        raise ValueError(f"データが少なすぎます（最低{seq_len + forecast_horizon + 1}日分必要）")

    data = df.copy()
    feats = pd.DataFrame(index=data.index)

    feats["close_return"] = data["Close"].pct_change()
    feats["volume_return"] = data["Volume"].pct_change().clip(-5, 5)

    delta = data["Close"].diff()
    gain = delta.where(delta > 0, 0.0)
    loss = (-delta).where(delta < 0, 0.0)
    avg_gain = gain.ewm(alpha=1.0 / 14, min_periods=14, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1.0 / 14, min_periods=14, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    rsi = 100.0 - (100.0 / (1.0 + rs))
    rsi.loc[avg_loss == 0] = 100.0
    feats["rsi"] = rsi / 100.0

    ema_12 = data["Close"].ewm(span=12, adjust=False).mean()
    ema_26 = data["Close"].ewm(span=26, adjust=False).mean()
    macd = ema_12 - ema_26
    signal = macd.ewm(span=9, adjust=False).mean()
    feats["macd_hist"] = (macd - signal) / data["Close"]

    sma_20 = data["Close"].rolling(20).mean()
    std_20 = data["Close"].rolling(20).std()
    bb_upper = sma_20 + std_20 * 2
    bb_lower = sma_20 - std_20 * 2
    bb_range = (bb_upper - bb_lower).replace(0, np.nan)
    feats["bb_position"] = ((data["Close"] - bb_lower) / bb_range).clip(0, 1)

    feats["sma5_diff"] = (data["Close"] / data["Close"].rolling(5).mean() - 1).clip(-0.2, 0.2)
    feats["sma20_diff"] = (data["Close"] / sma_20 - 1).clip(-0.2, 0.2)
    feats["high_low_range"] = ((data["High"] - data["Low"]) / data["Close"]).clip(0, 0.2)

    feats = feats.replace([np.inf, -np.inf], np.nan)

    if predict_mode:
        # 🔧 build_feature_matrix と同じ修正（本関数側にも Market Lens 由来のバグがあった）:
        # ターゲット（未来 forecast_horizon 日先リターン）を計算してから dropna すると、
        # 直近 forecast_horizon 日分が「ターゲットが NaN」という理由だけで失われ、本番当日の
        # 推論に使うべき最新シーケンスが欠落し得る。predict_mode ではターゲットを一切
        # 計算せず特徴量列のみで dropna することで、最新日を含む窓を確実に返す。
        feats_only = feats.dropna()
        if len(feats_only) < seq_len:
            raise ValueError("NaN 除去後のデータが不足しています")
        x = feats_only.to_numpy()[-seq_len:][np.newaxis, :]
        return x, None, feats_only.index[-1:]

    target = data["Close"].pct_change(periods=forecast_horizon).shift(-forecast_horizon)

    combined = feats.copy()
    combined["_target"] = target
    combined = combined.dropna()

    if len(combined) < seq_len + 1:
        raise ValueError("NaN 除去後のデータが不足しています")

    feature_cols = [c for c in combined.columns if c != "_target"]
    feat_arr = combined[feature_cols].to_numpy()
    target_arr = combined["_target"].to_numpy()

    n_samples = len(feat_arr) - seq_len - forecast_horizon + 1
    if n_samples <= 0:
        raise ValueError("シーケンス生成後にサンプルが0件になりました")

    x_list = [feat_arr[i : i + seq_len] for i in range(n_samples)]
    y_list = [target_arr[i + seq_len - 1] for i in range(n_samples)]

    x = np.array(x_list, dtype=np.float32)
    y = np.array(y_list, dtype=np.float32)
    # 各サンプルのターゲット日付。y_list[i] は target_arr[i + seq_len - 1] に対応するため、
    # combined.index を同じ添字でスライスする。
    dates = combined.index[seq_len - 1 : seq_len - 1 + n_samples]

    return x, y, dates
