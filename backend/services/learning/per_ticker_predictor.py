"""銘柄別モデル（P9）: XGBoost / RandomForest による株価予測モデル.

Market Lens `backend/services/ml_predictor.py` から移植、変更点: `objective="classification"`
（トリプルバリア2値分類）・マクロ指標特徴量・`feature_version` は移植しない（回帰専用、
`plans/04_タスクリスト.md` P9 参照。Alpha Forge の `feature_engineering.build_feature_matrix`
自体が回帰パスのみを持つ）。`model_dir` の既定値は `pool_training_service.py` と同じ規約
（リポジトリ直下 `data/models/`）に揃えた。
"""

from __future__ import annotations

import os
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Protocol

import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestRegressor
from sklearn.metrics import mean_absolute_error, mean_squared_error
from xgboost import XGBRegressor

from backend.services.learning.feature_engineering import build_feature_matrix
from backend.services.learning.predictor_protocol import Hyperparams, PredictionOutput
from backend.services.learning.ts_validation import purged_train_val_split
from backend.services.ledger.skill_metrics import naive_rmse as _naive_rmse
from backend.services.ledger.skill_metrics import skill_score as _skill_score

__all__ = ["BasePredictor", "RandomForestPredictor", "XGBoostPredictor"]

# 95%信頼区間を正規分布近似で得るためのzスコア（±1.96σ）
_CONFIDENCE_Z_SCORE = 1.96
# residual_std を持たない旧モデル用の固定信頼区間フォールバック値
_FALLBACK_CONFIDENCE_INTERVAL = 0.02
# train/val分割で末尾から検証に回す比率（DL側の dl/base.py と揃える）
_DEFAULT_VAL_RATIO = 0.15
# 保存フォーマットのバージョン（将来の payload 変更検出用）
_FORMAT_VERSION = 1
# MAPE算出時に実測値をゼロ近傍とみなして除外する閾値（分母発散を防ぐ、dl/base.py と同じ考え方）
_MAPE_ZERO_EPSILON = 1e-8

# pool_training_service.py の _MODEL_DIR と同じ規約（このファイルから見てリポジトリ直下 data/models）
_DEFAULT_MODEL_DIR = Path(__file__).resolve().parents[3] / "data" / "models"


def _safe_mape(y_true: np.ndarray | pd.Series, y_pred: np.ndarray) -> float:
    """MAPE（平均絶対パーセント誤差）を算出する（実測値ゼロ近傍のサンプルは除外する）."""
    y_true_arr = np.asarray(y_true, dtype=float)
    y_pred_arr = np.asarray(y_pred, dtype=float)
    mask = np.abs(y_true_arr) > _MAPE_ZERO_EPSILON
    if not mask.any():
        return 0.0
    return float(np.mean(np.abs((y_true_arr[mask] - y_pred_arr[mask]) / y_true_arr[mask])))


def _iso_date(value: object) -> str:
    """pandas Timestamp 等の日付ライクな値を ISO 日付文字列（YYYY-MM-DD）に変換する.

    train()/evaluate_on() が記録する eval_start/eval_end は品質ゲートでの
    日付区間比較に使うため、型に依らず一貫した文字列表現へ揃える。
    """
    if isinstance(value, pd.Timestamp):
        return value.date().isoformat()
    return str(value)


class _SklearnLikeModel(Protocol):
    """fit/predict を持つモデルの最小インターフェース."""

    def fit(self, X: pd.DataFrame, y: pd.Series) -> object: ...
    def predict(self, X: pd.DataFrame) -> np.ndarray: ...


class BasePredictor(ABC):
    """銘柄別回帰モデルの共通インターフェース."""

    def __init__(self, model_dir: str | None = None) -> None:
        self.model: _SklearnLikeModel | None = None
        self.model_dir = model_dir or str(_DEFAULT_MODEL_DIR)
        os.makedirs(self.model_dir, exist_ok=True)
        # 検証残差の標準偏差。学習後に held-out val 上で算出し、
        # 推論時の動的信頼区間の基準にする（旧形式ロード時は None）
        self.residual_std: float | None = None

    @abstractmethod
    def _create_model(self, hyperparams: Hyperparams) -> _SklearnLikeModel:
        """回帰モデルインスタンスを生成する."""
        raise NotImplementedError

    def train(
        self, df: pd.DataFrame, hyperparams: Hyperparams, forecast_horizon: int = 5
    ) -> dict[str, float | str | int | bool]:
        """時系列 train/val 分割で学習し、held-out 検証データ上の指標を返す（テンプレートメソッド）.

        XGBoost/RandomForest で唯一異なるのはモデル生成（_create_model）だけなので、
        分割・学習・残差算出・再学習という共通の骨組みをここに集約する（DRY）。
        purged_train_val_split で時系列分割することで、「全データにfitし同一データで
        評価する」リーク的評価を解消する。
        """
        # gap は「ラベルが未来を参照する日数」= forecast_horizon 日先リターン。train終端の
        # 直近 gap 件のラベルが val 期間の価格に依存するため、その重なりを断つ（リーク防止）。
        gap = forecast_horizon

        X, y = build_feature_matrix(df, forecast_horizon=forecast_horizon)
        if y is None:
            raise RuntimeError("predict_mode=False であれば y は必ず生成される")

        # purged_train_val_split は ndarray 前提だが、sklearn/xgboost に ndarray を渡すと
        # 「X does not have valid feature names」警告が出る。分割位置だけ同関数から得て、
        # fit/predict には特徴量名を保持した DataFrame/Series を iloc で渡す。
        X_train_arr, _, X_val_arr, _ = purged_train_val_split(
            X.to_numpy(), y.to_numpy(), val_ratio=_DEFAULT_VAL_RATIO, gap=gap
        )
        n = len(X)
        train_size = len(X_train_arr)
        val_size = len(X_val_arr)
        X_train = X.iloc[:train_size]
        y_train = y.iloc[:train_size]
        X_val = X.iloc[n - val_size :]
        y_val = y.iloc[n - val_size :]

        # まず train 分割のみで学習し、held-out val で指標を測る
        self.model = self._create_model(hyperparams)
        self.model.fit(X_train, y_train)

        val_pred = self.model.predict(X_val)
        # 残差は必ず held-out val から計算する（in-sample では楽観的すぎるため）
        self.residual_std = float(np.std(y_val.to_numpy() - val_pred))
        metrics: dict[str, float | str | int | bool] = dict(self._calculate_metrics(y_val, val_pred))

        # 品質ゲート（per_ticker_training_service._apply_quality_gate）が「新旧モデルの
        # 検証窓がずれたまま RMSE を比較してしまう」問題を避けられるよう、この学習で
        # 実際に使った val 区間の日付を記録する（evaluate_on で同じ窓に旧モデルを揃える）。
        metrics["eval_start"] = _iso_date(X_val.index[0])
        metrics["eval_end"] = _iso_date(X_val.index[-1])
        metrics["val_rows"] = int(val_size)
        # 保存されるモデルは以下で全データ再学習したものであり、上記 metrics は
        # その一つ前（train分割のみ）のモデルの held-out 評価である事実を明記する。
        metrics["refit_full"] = True

        # 本番推論用の最終モデルは全データで再学習する。直近（val期間）のデータほど
        # 近い将来の予測に有用であり、残差は上記の hold-out で測定済みのためリークにならない。
        self.model = self._create_model(hyperparams)
        self.model.fit(X, y)

        return metrics

    def predict(self, df: pd.DataFrame, forecast_horizon: int = 5) -> PredictionOutput:
        """直近のデータから将来を予測する.

        信頼区間は学習時の検証残差（residual_std）から動的に算出する。
        residual_std を持たない旧形式モデルでは固定値へフォールバックする。
        """
        if self.model is None:
            raise ValueError("モデルがロードまたは学習されていません")

        X, _ = build_feature_matrix(df, forecast_horizon=forecast_horizon, predict_mode=True)

        latest_X = X.iloc[[-1]]
        current_price = float(df["Close"].iloc[-1])

        prediction = float(self.model.predict(latest_X)[0])
        predicted_price = current_price * (1.0 + prediction)

        if self.residual_std is not None:
            confidence = _CONFIDENCE_Z_SCORE * self.residual_std
        else:
            confidence = _FALLBACK_CONFIDENCE_INTERVAL

        return {
            "target_date": "TBD",  # 呼び出し側（ルーター等）でカレンダー計算して埋める想定
            "predicted_close": predicted_price,
            "prediction_rate": prediction,
            "confidence_lower": predicted_price * (1.0 - confidence),
            "confidence_upper": predicted_price * (1.0 + confidence),
            "residual_std": self.residual_std,
        }

    def save(self, version: str) -> str:
        """モデルと検証残差を辞書形式でディスクに保存し、パスを返す."""
        if self.model is None:
            raise ValueError("学習済みモデルが存在しません")

        file_path = os.path.join(self.model_dir, f"{self.__class__.__name__}_{version}.joblib")
        payload = {
            "format_version": _FORMAT_VERSION,
            "model": self.model,
            "residual_std": self.residual_std,
        }
        joblib.dump(payload, file_path)
        return file_path

    def load(self, file_path: str) -> None:
        """ディスクからモデルを読み込む."""
        if not os.path.exists(file_path):
            raise FileNotFoundError(f"モデルファイルが見つかりません: {file_path}")

        loaded = joblib.load(file_path)
        self.model = loaded["model"]
        self.residual_std = loaded.get("residual_std")

    def _calculate_metrics(self, y_true: np.ndarray | pd.Series, y_pred: np.ndarray) -> dict[str, float]:
        """評価指標を計算する.

        rmse/mae/mape に加え、「変化率0（明日も今日と同じ）」と予測し続けるナイーブモデル
        に対する改善度（naive_rmse・skill）も返す。rmse 単体では良否が判断できないため
        （2026-09時点の Market Lens オフライン検証で active XGBoost モデルの74%がナイーブ
        予測より悪いことが判明済み）、これを恒久的に記録する。
        """
        rmse = float(np.sqrt(mean_squared_error(y_true, y_pred)))
        naive = _naive_rmse(np.asarray(y_true, dtype=float))
        return {
            "rmse": rmse,
            "mae": float(mean_absolute_error(y_true, y_pred)),
            "mape": _safe_mape(y_true, y_pred),
            "naive_rmse": naive,
            "skill": _skill_score(rmse, naive),
        }

    def evaluate_on(self, df: pd.DataFrame, start: str, end: str, forecast_horizon: int = 5) -> dict[str, float]:
        """学習済み/ロード済みモデルを指定した日付区間で再評価する.

        日次バッチの品質ゲートは「毎日ずれる取得期間で val 区間が揺れ、たまたま静かな
        検証窓を引いた新モデルが有利になる」問題を抱える。新モデルの eval_start/eval_end
        （train() が metrics に記録する）を渡して旧モデルをここで同じ窓で評価し直すことで、
        フェアな比較にする。
        """
        if self.model is None:
            raise ValueError("モデルがロードまたは学習されていません")

        X, y = build_feature_matrix(df, forecast_horizon=forecast_horizon)
        if y is None:
            raise RuntimeError("predict_mode=False であれば y は必ず生成される")

        start_ts = pd.Timestamp(start)
        end_ts = pd.Timestamp(end)
        mask = (X.index >= start_ts) & (X.index <= end_ts)
        X_window = X.loc[mask]
        y_window = y.loc[mask]
        if len(X_window) == 0:
            raise ValueError(f"指定区間にサンプルがありません（start={start}, end={end}）")

        pred = self.model.predict(X_window)
        return self._calculate_metrics(y_window, pred)


class XGBoostPredictor(BasePredictor):
    """XGBoostを用いた株価変化率予測モデル."""

    def _create_model(self, hyperparams: Hyperparams) -> _SklearnLikeModel:
        params: Hyperparams = {
            "n_estimators": 100,
            "learning_rate": 0.1,
            "max_depth": 5,
            "subsample": 0.8,
            "random_state": 42,
        }
        params.update(hyperparams)
        return XGBRegressor(**params)


class RandomForestPredictor(BasePredictor):
    """Random Forestを用いた株価変化率予測モデル."""

    def _create_model(self, hyperparams: Hyperparams) -> _SklearnLikeModel:
        params: Hyperparams = {
            "n_estimators": 100,
            "max_depth": 5,
            "min_samples_split": 2,
            "random_state": 42,
        }
        params.update(hyperparams)
        return RandomForestRegressor(**params)
