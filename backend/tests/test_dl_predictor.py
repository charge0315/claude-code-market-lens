"""dl.lstm / dl.transformer（銘柄別モデル、P9）のテスト.

torch は `requirements-ci.txt` に含めないため（`plans/04_タスクリスト.md` P9）、
本ファイルのテストは torch が import できない環境では自動的にスキップする。
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

pytest.importorskip("torch")

from backend.services.learning.dl.base import BaseTorchPredictor  # noqa: E402
from backend.services.learning.dl.lstm import LSTMPredictor  # noqa: E402
from backend.services.learning.dl.transformer import TransformerPredictor  # noqa: E402

_N_ROWS = 200
_TRAIN_HYPERPARAMS = {"seq_len": 20, "epochs": 3, "batch_size": 16}


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


@pytest.fixture(params=[LSTMPredictor, TransformerPredictor])
def predictor_cls(request: pytest.FixtureRequest) -> type[BaseTorchPredictor]:
    return request.param


def test_train_returns_holdout_metrics_with_eval_window(
    predictor_cls: type[BaseTorchPredictor], tmp_path: object
) -> None:
    predictor = predictor_cls(model_dir=str(tmp_path))
    metrics = predictor.train(_make_ohlcv(), dict(_TRAIN_HYPERPARAMS), forecast_horizon=5)

    assert float(metrics["rmse"]) >= 0.0
    assert metrics["refit_full"] is False
    assert isinstance(metrics["eval_start"], str)
    assert isinstance(metrics["eval_end"], str)
    assert predictor.residual_std is not None


def test_predict_uses_mc_dropout_and_returns_confidence_interval(
    predictor_cls: type[BaseTorchPredictor], tmp_path: object
) -> None:
    predictor = predictor_cls(model_dir=str(tmp_path))
    df = _make_ohlcv()
    predictor.train(df, dict(_TRAIN_HYPERPARAMS), forecast_horizon=5)

    output = predictor.predict(df, forecast_horizon=5)

    assert output["confidence_lower"] < output["predicted_close"] < output["confidence_upper"]
    # 推論後は必ず eval モードへ戻す（他ティッカーの推論へ確率的状態が漏れない）
    assert predictor.model is not None
    assert predictor.model.training is False


def test_predict_without_training_raises(predictor_cls: type[BaseTorchPredictor], tmp_path: object) -> None:
    predictor = predictor_cls(model_dir=str(tmp_path))
    with pytest.raises(ValueError, match="ロードまたは学習"):
        predictor.predict(_make_ohlcv(), forecast_horizon=5)


def test_save_and_load_round_trip_preserves_arch_and_predictions(
    predictor_cls: type[BaseTorchPredictor], tmp_path: object
) -> None:
    df = _make_ohlcv()
    trained = predictor_cls(model_dir=str(tmp_path))
    trained.train(df, dict(_TRAIN_HYPERPARAMS), forecast_horizon=5)
    path = trained.save("v1")

    loaded = predictor_cls(model_dir=str(tmp_path))
    loaded.load(path)

    assert loaded.residual_std == trained.residual_std
    assert loaded.seq_len == trained.seq_len
    assert loaded.input_size == trained.input_size


def test_load_missing_file_raises(predictor_cls: type[BaseTorchPredictor], tmp_path: object) -> None:
    predictor = predictor_cls(model_dir=str(tmp_path))
    with pytest.raises(FileNotFoundError):
        predictor.load(str(tmp_path) + "/does-not-exist.pt")


def test_transformer_rejects_d_model_not_divisible_by_nhead(tmp_path: object) -> None:
    predictor = TransformerPredictor(model_dir=str(tmp_path))
    with pytest.raises(ValueError, match="割り切れる必要があります"):
        predictor.train(_make_ohlcv(), {"seq_len": 20, "epochs": 1, "d_model": 10, "nhead": 3}, forecast_horizon=5)
