"""ensemble_predictor（銘柄別モデルの重み付けアンサンブル、P9）のテスト.

実モデルの学習は重いため、`PredictorProtocol` を満たす軽量フェイクで
重み付け・クリップ・残差合成のロジックのみを検証する。
"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping

import pandas as pd
import pytest

from backend.services.learning.ensemble_predictor import (
    InsufficientModelsError,
    predict_ensemble_sync,
)
from backend.services.learning.predictor_protocol import Hyperparams, PredictionOutput


class _FakePredictor:
    """`PredictorProtocol` を満たす、固定予測値を返すテスト用フェイク."""

    def __init__(self, prediction_rate: float, residual_std: float | None) -> None:
        self._prediction_rate = prediction_rate
        self._residual_std = residual_std

    def train(
        self, df: pd.DataFrame, hyperparams: Hyperparams, forecast_horizon: int = 5
    ) -> dict[str, float | str | int | bool]:
        raise NotImplementedError

    def predict(self, df: pd.DataFrame, forecast_horizon: int = 5) -> PredictionOutput:
        current_price = float(df["Close"].iloc[-1])
        predicted_price = current_price * (1.0 + self._prediction_rate)
        return {
            "target_date": "TBD",
            "predicted_close": predicted_price,
            "prediction_rate": self._prediction_rate,
            "confidence_lower": predicted_price * 0.98,
            "confidence_upper": predicted_price * 1.02,
            "residual_std": self._residual_std,
        }

    def save(self, version: str) -> str:
        raise NotImplementedError

    def load(self, file_path: str) -> None:
        return None


def _row(rmse: float | None) -> dict[str, object]:
    metrics: dict[str, object] = {} if rmse is None else {"rmse": rmse}
    return {"artifact_path": "dummy.joblib", "val_metrics": json.dumps(metrics)}


def _df() -> pd.DataFrame:
    return pd.DataFrame({"Close": [100.0, 101.0, 102.0]})


def _get_predictor_factory(
    predictors: Mapping[str, _FakePredictor],
) -> Callable[[str], _FakePredictor]:
    def _get(model_type: str) -> _FakePredictor:
        return predictors[model_type]

    return _get


def test_raises_when_fewer_than_two_models_available() -> None:
    predictors = {"xgboost": _FakePredictor(0.01, 0.01)}
    model_rows = {"xgboost": _row(0.01)}

    with pytest.raises(InsufficientModelsError):
        predict_ensemble_sync(model_rows, _df(), 5, _get_predictor_factory(predictors))


def test_lower_rmse_model_gets_larger_weight() -> None:
    # xgboost: 高精度（rmse小）→ 大きい重み。random_forest: 低精度（rmse大）→ 小さい重み。
    predictors = {
        "xgboost": _FakePredictor(prediction_rate=0.10, residual_std=0.01),
        "random_forest": _FakePredictor(prediction_rate=-0.10, residual_std=0.01),
    }
    model_rows = {"xgboost": _row(0.01), "random_forest": _row(0.05)}

    result, components = predict_ensemble_sync(model_rows, _df(), 5, _get_predictor_factory(predictors))

    assert set(components) == {"xgboost", "random_forest"}
    # 合成予測率は高精度モデル（+0.10）側に寄るはず（等重みなら0になる）
    assert result["prediction_rate"] > 0.0


def test_missing_rmse_falls_back_to_equal_weight() -> None:
    predictors = {
        "xgboost": _FakePredictor(prediction_rate=0.10, residual_std=0.01),
        "random_forest": _FakePredictor(prediction_rate=-0.10, residual_std=0.01),
    }
    model_rows = {"xgboost": _row(None), "random_forest": _row(None)}

    result, _components = predict_ensemble_sync(model_rows, _df(), 5, _get_predictor_factory(predictors))

    # 両モデルとも重み1.0（等重み）のため合成予測率はちょうど中間になる
    assert result["prediction_rate"] == pytest.approx(0.0, abs=1e-9)


def test_weight_ratio_is_capped_to_prevent_single_model_dominance() -> None:
    predictors = {
        "xgboost": _FakePredictor(prediction_rate=1.0, residual_std=0.01),
        "random_forest": _FakePredictor(prediction_rate=0.0, residual_std=0.01),
        "lstm": _FakePredictor(prediction_rate=0.0, residual_std=0.01),
    }
    # xgboostのRMSEを極端に小さくすると、クリップが無ければ実質1モデルに収束してしまう
    model_rows = {"xgboost": _row(1e-9), "random_forest": _row(1.0), "lstm": _row(1.0)}

    result, _components = predict_ensemble_sync(model_rows, _df(), 5, _get_predictor_factory(predictors))

    # クリップ（最大5倍）により、xgboost単独の予測率1.0そのものにはならない
    assert result["prediction_rate"] < 1.0


def test_model_load_or_predict_failure_is_skipped_not_fatal() -> None:
    class _BrokenPredictor(_FakePredictor):
        def predict(self, df: pd.DataFrame, forecast_horizon: int = 5) -> PredictionOutput:
            raise RuntimeError("推論失敗")

    predictors = {
        "xgboost": _BrokenPredictor(0.0, 0.01),
        "random_forest": _FakePredictor(0.05, 0.01),
        "lstm": _FakePredictor(0.05, 0.01),
    }
    model_rows = {"xgboost": _row(0.01), "random_forest": _row(0.01), "lstm": _row(0.01)}

    result, components = predict_ensemble_sync(model_rows, _df(), 5, _get_predictor_factory(predictors))

    assert "xgboost" not in components
    assert set(components) == {"random_forest", "lstm"}
    assert result["prediction_rate"] == pytest.approx(0.05, abs=1e-9)


def test_residual_std_combines_via_variance_addition() -> None:
    predictors = {
        "xgboost": _FakePredictor(0.0, residual_std=0.03),
        "random_forest": _FakePredictor(0.0, residual_std=0.04),
    }
    model_rows = {"xgboost": _row(0.01), "random_forest": _row(0.01)}

    result, _components = predict_ensemble_sync(model_rows, _df(), 5, _get_predictor_factory(predictors))

    # 等重み（w=0.5ずつ）: sqrt((0.5*0.03)^2 + (0.5*0.04)^2)
    expected = ((0.5 * 0.03) ** 2 + (0.5 * 0.04) ** 2) ** 0.5
    assert result["residual_std"] == pytest.approx(expected)


def test_residual_std_is_none_when_any_component_missing_it() -> None:
    predictors = {
        "xgboost": _FakePredictor(0.0, residual_std=None),
        "random_forest": _FakePredictor(0.0, residual_std=0.04),
    }
    model_rows = {"xgboost": _row(0.01), "random_forest": _row(0.01)}

    result, _components = predict_ensemble_sync(model_rows, _df(), 5, _get_predictor_factory(predictors))

    assert result["residual_std"] is None
