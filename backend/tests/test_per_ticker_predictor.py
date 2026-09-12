"""per_ticker_predictor（銘柄別 XGBoost / RandomForest モデル、P9）のテスト.

Market Lens `backend/tests/test_ml_predictor.py` 相当。回帰専用（objective="classification"・
マクロ特徴量は移植していない）のため、それらのテストは対象外。
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from backend.services.learning.per_ticker_predictor import (
    BasePredictor,
    RandomForestPredictor,
    XGBoostPredictor,
)

_N_ROWS = 300


def _make_ohlcv(n: int = _N_ROWS) -> pd.DataFrame:
    """再現可能な擬似ランダムウォークの OHLCV データフレームを生成する."""
    rng = np.random.default_rng(42)
    dates = pd.bdate_range("2023-01-01", periods=n)
    close = 1000.0 + np.cumsum(rng.normal(0, 5, size=n))
    close = np.abs(close) + 100.0
    high = close + rng.uniform(0, 5, size=n)
    low = close - rng.uniform(0, 5, size=n)
    open_ = close + rng.uniform(-3, 3, size=n)
    volume = rng.uniform(1_000_000, 5_000_000, size=n)
    return pd.DataFrame({"Open": open_, "High": high, "Low": low, "Close": close, "Volume": volume}, index=dates)


@pytest.fixture(params=[XGBoostPredictor, RandomForestPredictor])
def predictor_cls(request: pytest.FixtureRequest) -> type[BasePredictor]:
    return request.param


def test_train_returns_holdout_metrics_with_eval_window(predictor_cls: type[BasePredictor], tmp_path: object) -> None:
    predictor = predictor_cls(model_dir=str(tmp_path))
    metrics = predictor.train(_make_ohlcv(), {}, forecast_horizon=5)

    assert float(metrics["rmse"]) >= 0.0
    assert metrics["refit_full"] is True
    assert isinstance(metrics["eval_start"], str)
    assert isinstance(metrics["eval_end"], str)
    assert int(metrics["val_rows"]) > 0
    # 残差は held-out val 由来（学習直後は必ず設定される）
    assert predictor.residual_std is not None


def test_predict_returns_dynamic_confidence_interval_from_residual_std(
    predictor_cls: type[BasePredictor], tmp_path: object
) -> None:
    predictor = predictor_cls(model_dir=str(tmp_path))
    df = _make_ohlcv()
    predictor.train(df, {}, forecast_horizon=5)

    output = predictor.predict(df, forecast_horizon=5)
    residual_std = predictor.residual_std
    assert residual_std is not None

    assert output["residual_std"] == residual_std
    assert output["confidence_lower"] < output["predicted_close"] < output["confidence_upper"]
    expected_width = 1.96 * residual_std * output["predicted_close"]
    assert output["confidence_upper"] - output["predicted_close"] == pytest.approx(expected_width, rel=1e-6)


def test_predict_without_training_raises(predictor_cls: type[BasePredictor], tmp_path: object) -> None:
    predictor = predictor_cls(model_dir=str(tmp_path))
    with pytest.raises(ValueError, match="ロードまたは学習"):
        predictor.predict(_make_ohlcv(), forecast_horizon=5)


def test_save_and_load_round_trip_preserves_residual_std_and_predictions(
    predictor_cls: type[BasePredictor], tmp_path: object
) -> None:
    df = _make_ohlcv()
    trained = predictor_cls(model_dir=str(tmp_path))
    trained.train(df, {}, forecast_horizon=5)
    path = trained.save("v1")
    expected = trained.predict(df, forecast_horizon=5)

    loaded = predictor_cls(model_dir=str(tmp_path))
    loaded.load(path)

    assert loaded.residual_std == trained.residual_std
    actual = loaded.predict(df, forecast_horizon=5)
    assert actual["predicted_close"] == pytest.approx(expected["predicted_close"])


def test_load_missing_file_raises(predictor_cls: type[BasePredictor], tmp_path: object) -> None:
    predictor = predictor_cls(model_dir=str(tmp_path))
    with pytest.raises(FileNotFoundError):
        predictor.load(str(tmp_path) + "/does-not-exist.joblib")


def test_evaluate_on_reevaluates_same_window_reported_by_train(
    predictor_cls: type[BasePredictor], tmp_path: object
) -> None:
    df = _make_ohlcv()
    predictor = predictor_cls(model_dir=str(tmp_path))
    metrics = predictor.train(df, {}, forecast_horizon=5)

    rewindow = predictor.evaluate_on(df, str(metrics["eval_start"]), str(metrics["eval_end"]), forecast_horizon=5)

    # 全データ再学習後のモデルで再評価するため、held-out val 時点の RMSE と厳密一致はしないが、
    # 同じサンプル数のオーダーで有限値が返ることを確認する。
    assert rewindow["rmse"] >= 0.0


def test_evaluate_on_raises_when_window_has_no_samples(predictor_cls: type[BasePredictor], tmp_path: object) -> None:
    df = _make_ohlcv()
    predictor = predictor_cls(model_dir=str(tmp_path))
    predictor.train(df, {}, forecast_horizon=5)

    with pytest.raises(ValueError, match="指定区間にサンプルがありません"):
        predictor.evaluate_on(df, "1990-01-01", "1990-01-02", forecast_horizon=5)
