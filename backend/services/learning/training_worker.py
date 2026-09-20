"""子プロセスで実行される学習ワーカー関数（🆕 ProcessPoolExecutor 並列化）.

`ProcessPoolExecutor` は Windows では `spawn` 起動方式のため、渡す関数はモジュール
トップレベルであることが必須（クロージャ・インスタンスメソッドは pickle できない）。
このモジュールは学習・保存という CPU バウンドな計算のみを行い、ネットワーク I/O・DB
アクセスは一切行わない（`per_ticker_training_service.py` 側の親プロセス asyncio ループが
担当する）。torch モデルオブジェクト自体もプロセス境界を越えて受け渡さない（子プロセス内で
生成・破棄する）ことで、torch オブジェクトの pickle 可否を気にする必要がない設計にしている。

`spawn` は子プロセス起動時にこのモジュールを再 import するため、import 時に重い副作用
（DB 接続確立等）を起こすモジュールは意図的に import しない — `backend.services.db.database`
（モジュールグローバル `AsyncEngine`）を直接・間接に import するモジュールは import 禁止。
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from backend.services.learning.dl.lstm import LSTMPredictor
from backend.services.learning.dl.transformer import TransformerPredictor
from backend.services.learning.per_ticker_predictor import RandomForestPredictor, XGBoostPredictor
from backend.services.learning.predictor_protocol import PredictorProtocol


def _get_predictor(model_type: str) -> PredictorProtocol:
    """モデルタイプ文字列から対応する predictor インスタンスを返す（`get_predictor` の複製）.

    `per_ticker_training_service.py` から import すると、そのモジュールが `training_batch_db`/
    `model_registry_db`（DB アクセス）を import している都合で spawn 時の import 安全性が
    保証できなくなるため、この小さな工場関数のみ意図的に複製する。
    """
    if model_type == "xgboost":
        return XGBoostPredictor()
    if model_type == "random_forest":
        return RandomForestPredictor()
    if model_type == "lstm":
        return LSTMPredictor()
    if model_type == "transformer":
        return TransformerPredictor()
    raise ValueError(f"Unsupported model type: {model_type}")


@dataclass(frozen=True)
class TrainWorkerResult:
    """子プロセスから親プロセスへ返す学習結果（プリミティブ型のみ、pickle 安全）."""

    ticker: str
    metrics: dict[str, float | str | int | bool]
    artifact_path: str
    # 既存 champion を新モデルと同じ評価窓で再評価した RMSE（既存 champion が無い、または
    # 再評価に失敗した場合は None。呼び出し元は記録済み RMSE へフォールバックする）。
    comparison_rmse: float | None


def train_ticker_in_subprocess(
    *,
    ticker: str,
    model_type: str,
    version: str,
    df: pd.DataFrame,
    forecast_horizon: int,
    existing_artifact_path: str | None,
) -> TrainWorkerResult:
    """1 銘柄を学習・保存し、（既存 champion があれば）同一窓で再評価する同期関数.

    `ProcessPoolExecutor`（本番）または `loop.run_in_executor(None, ...)` のデフォルト
    スレッドプール（テスト時、`per_ticker_training_service._create_worker_pool` が None を
    返すよう差し替えられている場合）のどちらからも同じインターフェースで呼べる。
    """
    predictor = _get_predictor(model_type)
    metrics = predictor.train(df, {}, forecast_horizon=forecast_horizon)
    artifact_path = predictor.save(version)

    comparison_rmse: float | None = None
    eval_start = metrics.get("eval_start")
    eval_end = metrics.get("eval_end")
    if existing_artifact_path and isinstance(eval_start, str) and isinstance(eval_end, str):
        try:
            existing_predictor = _get_predictor(model_type)
            existing_predictor.load(existing_artifact_path)
            rewindow_metrics = existing_predictor.evaluate_on(df, eval_start, eval_end)
            comparison_rmse = rewindow_metrics.get("rmse")
        except Exception:  # noqa: BLE001 - 再評価失敗は致命的ではない（親側が記録済みRMSEへフォールバック）
            comparison_rmse = None

    return TrainWorkerResult(
        ticker=ticker, metrics=metrics, artifact_path=artifact_path, comparison_rmse=comparison_rmse
    )
