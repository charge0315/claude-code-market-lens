"""feature_engineering（断面プール・銘柄別モデル向け特徴量生成）のテスト.

Market Lens 版の v2（唯一の挙動として移植）に対応するテストのみを移植し、
v1 バイト互換・objective="classification" 関連のテストは落とした。`predict_mode` の
直近日欠落バグ修正（🔧）を固定するテストを追加した。`build_sequence_matrix`（P9、
銘柄別 LSTM/Transformer 用）のテストも本ファイルに追加する。
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from backend.services.learning.feature_engineering import build_feature_matrix, build_sequence_matrix

_N_ROWS = 120


def _make_ohlcv(n: int = _N_ROWS) -> pd.DataFrame:
    """再現可能な擬似ランダムウォークの OHLCV データフレームを生成する."""
    rng = np.random.default_rng(42)
    dates = pd.bdate_range("2024-01-01", periods=n)
    close = 1000.0 + np.cumsum(rng.normal(0, 5, size=n))
    close = np.abs(close) + 100.0
    high = close + rng.uniform(0, 5, size=n)
    low = close - rng.uniform(0, 5, size=n)
    open_ = close + rng.uniform(-3, 3, size=n)
    volume = rng.uniform(1_000_000, 5_000_000, size=n)
    return pd.DataFrame({"Open": open_, "High": high, "Low": low, "Close": close, "Volume": volume}, index=dates)


_EXPECTED_COLUMNS = [
    "return_lag_1",
    "volume_lag_1",
    "return_lag_2",
    "volume_lag_2",
    "return_lag_3",
    "volume_lag_3",
    "return_lag_4",
    "volume_lag_4",
    "return_lag_5",
    "volume_lag_5",
    "sma_5_diff",
    "sma_20_diff",
    "sma_50_diff",
    "ema_12_diff",
    "macd",
    "macd_signal",
    "macd_hist",
    "bb_width",
    "bb_position",
    "rsi_14",
    "volatility_5",
    "volatility_20",
    "day_of_week_sin",
    "day_of_week_cos",
    "month_sin",
    "month_cos",
]


def test_build_feature_matrix_column_names_and_order() -> None:
    X, _ = build_feature_matrix(_make_ohlcv())
    assert list(X.columns) == _EXPECTED_COLUMNS


def test_build_feature_matrix_cyclical_date_encoding_is_bounded() -> None:
    X, _ = build_feature_matrix(_make_ohlcv())
    for col in ("day_of_week_sin", "day_of_week_cos", "month_sin", "month_cos"):
        assert X[col].between(-1.0, 1.0).all()


def test_build_feature_matrix_macd_columns_are_normalized_by_close() -> None:
    X, _ = build_feature_matrix(_make_ohlcv())
    # macd/macd_signal は Close で無次元化されているため、絶対水準の EMA 差より十分小さい。
    assert (X["macd"].abs() < 1.0).all()
    assert (X["macd_signal"].abs() < 1.0).all()


def test_build_feature_matrix_regression_returns_matching_length_x_y() -> None:
    X, y = build_feature_matrix(_make_ohlcv(), forecast_horizon=5)
    assert y is not None
    assert len(X) == len(y)
    assert not X.isna().any().any()


def test_build_feature_matrix_predict_mode_keeps_most_recent_row() -> None:
    """🔧 直近 forecast_horizon 日分がターゲット起因の dropna で失われないことを固定する.

    Market Lens は panel_feature_service から predict_mode=False で呼んでいたため、本番当日の
    推論行（未来の実現リターンが無い）が常に欠落し得た。predict_mode=True はターゲットを
    生成せず特徴量のみで dropna するため、最新日を含む全行が残る。
    """
    df = _make_ohlcv()
    X_predict, y_predict = build_feature_matrix(df, forecast_horizon=5, predict_mode=True)
    X_train, _ = build_feature_matrix(df, forecast_horizon=5, predict_mode=False)

    assert y_predict is None
    assert X_predict.index[-1] == df.index[-1]
    assert X_train.index[-1] < df.index[-1]


def test_build_feature_matrix_raises_on_insufficient_history() -> None:
    with pytest.raises(ValueError, match="データが少なすぎます"):
        build_feature_matrix(_make_ohlcv(n=30))


# ---------------------------------------------------------------------------
# build_sequence_matrix（P9、銘柄別 LSTM/Transformer 用）
# ---------------------------------------------------------------------------


def test_build_sequence_matrix_shapes() -> None:
    df = _make_ohlcv(n=200)
    x, y, dates = build_sequence_matrix(df, seq_len=20, forecast_horizon=5)
    assert y is not None
    assert x.ndim == 3
    assert x.shape[0] == len(y) == len(dates)
    assert x.shape[1] == 20


def test_build_sequence_matrix_predict_mode_returns_single_latest_window() -> None:
    df = _make_ohlcv(n=200)
    x, y, dates = build_sequence_matrix(df, seq_len=20, forecast_horizon=5, predict_mode=True)
    assert y is None
    assert x.shape == (1, 20, x.shape[2])
    assert dates[-1] == df.index[-1]


def test_build_sequence_matrix_raises_on_insufficient_history() -> None:
    with pytest.raises(ValueError, match="データが少なすぎます"):
        build_sequence_matrix(_make_ohlcv(n=10), seq_len=20, forecast_horizon=5)
