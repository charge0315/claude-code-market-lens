"""銘柄別モデル（P9）の予測モデル共通の型定義とインターフェース.

Market Lens `backend/services/predictor_protocol.py` から移植、変更点: `objective`
（回帰/分類）を持たず回帰専用にした（`win_probability` キーも削除）。Alpha Forge の
銘柄別モデルはトリプルバリア分類ラベリング基盤を持ち込まない方針
（`plans/04_タスクリスト.md` P9、`per_ticker_predictor.py` docstring 参照）。

XGBoost/RandomForest（per_ticker_predictor.py）と LSTM/Transformer（dl/base.py）の
両方が同じ入出力の形（Hyperparams / PredictionOutput）と操作（train/predict/save/load）に
従うことを型レベルで保証するため、両モジュールから独立したこのファイルに定義を集約する。
双方が互いを import し合う循環 import を避ける狙いもある。
"""

from __future__ import annotations

from typing import Protocol, TypedDict

import pandas as pd

# ハイパーパラメータは値の型が数値・文字列・真偽値のいずれかになりうるため union で表現する
Hyperparams = dict[str, float | int | str | bool]


class PredictionOutput(TypedDict):
    """予測結果の構造（回帰専用）."""

    target_date: str
    predicted_close: float
    prediction_rate: float
    confidence_lower: float
    confidence_upper: float
    # held-out val 上の検証残差の標準偏差（学習時に算出・保存済み）。ensemble_predictor が
    # 検証 RMSE の逆数で重み付けする際、および将来 recommender が銘柄のボラティリティに
    # 応じて動的にスケールする際に使う。旧形式ペイロードでは None がありうる。
    residual_std: float | None


class PredictorProtocol(Protocol):
    """予測モデルが備えるべき共通インターフェース.

    per_ticker_predictor.BasePredictor と dl.base.BaseTorchPredictor は継承関係を持たないため、
    共通の抽象基底クラスではなく構造的部分型（Protocol）で「同じ操作ができる」ことを表現する。
    runtime_checkable は付与しない: isinstance() による実行時検査は現状不要であり、
    メソッドシグネチャ（引数の型・デフォルト値）までは検証できず誤った安心感を与えるため。
    """

    def train(
        self, df: pd.DataFrame, hyperparams: Hyperparams, forecast_horizon: int = 5
    ) -> dict[str, float | str | int | bool]:
        """モデルを学習し、評価メトリクスを返す.

        rmse/mae/mape 等の数値指標に加え、eval_start/eval_end（str）・val_rows（int）・
        refit_full（bool）等のメタ情報も含むため戻り値は union 型。
        """
        ...

    def predict(self, df: pd.DataFrame, forecast_horizon: int = 5) -> PredictionOutput:
        """直近のデータから将来の価格を予測する."""
        ...

    def save(self, version: str) -> str:
        """モデルをディスクに保存し、保存先パスを返す."""
        ...

    def load(self, file_path: str) -> None:
        """ディスクからモデルを読み込む."""
        ...

    def evaluate_on(self, df: pd.DataFrame, start: str, end: str, forecast_horizon: int = 5) -> dict[str, float]:
        """学習済み/ロード済みモデルを指定した日付区間で再評価する（品質ゲートの窓合わせ用）."""
        ...
