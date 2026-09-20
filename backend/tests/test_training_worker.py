"""training_worker.py（🆕 ProcessPoolExecutor 向け学習ワーカー関数）のテスト.

`train_ticker_in_subprocess` は純粋な同期関数のため、実際に子プロセスを起動せず直接
呼び出して検証する（並列化のウィンドウ処理オーケストレーション自体は
`test_per_ticker_training_service.py` 側でテスト済み）。モデル保存先の一時ディレクトリ
隔離は `conftest.py` の autouse fixture（`_isolated_per_ticker_model_dir`）が担う。
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from backend.services.learning import training_worker as worker


def _make_ohlcv(n: int = 300, seed: int = 42) -> pd.DataFrame:
    """再現可能・学習可能な OHLCV データフレームを生成する（周期パターン + 小さいノイズ）."""
    rng = np.random.default_rng(seed)
    dates = pd.bdate_range("2023-01-01", periods=n)
    t = np.arange(n)
    close = 1000.0 + 50.0 * np.sin(2 * np.pi * t / 20.0) + rng.normal(0, 0.5, size=n)
    high = close + rng.uniform(0, 1, size=n)
    low = close - rng.uniform(0, 1, size=n)
    open_ = close + rng.uniform(-0.5, 0.5, size=n)
    volume = rng.uniform(1_000_000, 5_000_000, size=n)
    return pd.DataFrame({"Open": open_, "High": high, "Low": low, "Close": close, "Volume": volume}, index=dates)


def test_train_ticker_in_subprocess_returns_metrics_and_artifact() -> None:
    df = _make_ohlcv()

    result = worker.train_ticker_in_subprocess(
        ticker="7203", model_type="xgboost", version="v1", df=df, forecast_horizon=5, existing_artifact_path=None
    )

    assert result.ticker == "7203"
    assert result.artifact_path
    assert "rmse" in result.metrics
    # 既存アーティファクトが無いため、比較用の再評価は行わない。
    assert result.comparison_rmse is None


def test_train_ticker_in_subprocess_computes_comparison_rmse_against_existing_artifact() -> None:
    df = _make_ohlcv()
    baseline = worker.train_ticker_in_subprocess(
        ticker="7203",
        model_type="xgboost",
        version="baseline",
        df=df,
        forecast_horizon=5,
        existing_artifact_path=None,
    )

    challenger = worker.train_ticker_in_subprocess(
        ticker="7203",
        model_type="xgboost",
        version="challenger",
        df=df,
        forecast_horizon=5,
        existing_artifact_path=baseline.artifact_path,
    )

    assert challenger.comparison_rmse is not None


def test_train_ticker_in_subprocess_returns_none_comparison_when_existing_artifact_missing() -> None:
    df = _make_ohlcv()

    result = worker.train_ticker_in_subprocess(
        ticker="7203",
        model_type="xgboost",
        version="v1",
        df=df,
        forecast_horizon=5,
        existing_artifact_path="/nonexistent/path.joblib",
    )

    # 再評価に失敗しても例外を伝播させず None を返す（呼び出し元が記録済みRMSEへフォールバックする）。
    assert result.comparison_rmse is None


def test_get_predictor_rejects_unsupported_model_type() -> None:
    with pytest.raises(ValueError, match="unsupported"):
        worker._get_predictor("unsupported")
