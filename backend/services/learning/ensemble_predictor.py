"""複数の銘柄別モデルの予測を重み付け平均するアンサンブル予測サービス（P9）.

Market Lens `backend/services/ensemble_predictor.py` から移植、変更点: 同期版
（`predict_ensemble_sync` 相当）のみを持つ。`services/scoring/ml_score_provider.py` の
`make_pool_ml_score_provider` と同じ理由（`recommender.compute_recommendation` は
`asyncio.to_thread` 経由の同期関数であり、非同期 DB I/O を実行中のイベントループが無い
スレッドから呼び出せない）で、呼び出し側が `model_registry_db` から事前取得した
`{model_type: row}`（`row` は `model_registry_db.get_model` の戻り値）を受け取ることで
非同期 I/O を一切行わずに済ませる。

アンサンブル自体は学習を行わない（train()を持たない）。既に学習・保存済みの
XGBoost/RandomForest/LSTM/Transformerの最新 champion をそれぞれロードして推論だけを行い、
検証RMSEの逆数で重み付け平均する。RMSEが小さい（＝held-out検証での精度が高い）
モデルほど大きな重みを持つ。
"""

from __future__ import annotations

import json
import logging
import math
from collections.abc import Callable, Mapping

import pandas as pd

from backend.services.learning.predictor_protocol import PredictionOutput, PredictorProtocol

logger = logging.getLogger(__name__)

PER_TICKER_MODEL_TYPES = ("xgboost", "random_forest", "lstm", "transformer")
# 少なくとも2種類のモデルが揃わなければ「アンサンブル」として意味を成さない。
MIN_COMPONENT_MODELS = 2
# 検証RMSEが極端に小さい場合に重みが発散しないための下限値
_MIN_RMSE_FOR_WEIGHTING = 1e-6
# 最大重み/最小重みの比率上限。RMSE逆数の重みは理論上無制限に発散しうるため、
# 1モデルだけが極端に小さいRMSEを持つ場合（過学習・たまたま検証データと相性が良かった等）に
# アンサンブルが実質その1モデルへ収束してしまい、「複数モデルの分散効果」という本来の目的を
# 損なう。5倍までなら「最も信頼できるモデルの意見を強めに反映しつつ、他モデルの意見も
# 無視しない」というアンサンブルの趣旨を保てる目安として採用する（Market Lens 踏襲）。
_MAX_WEIGHT_RATIO = 5.0


class InsufficientModelsError(RuntimeError):
    """アンサンブルに必要な最小モデル数（2種類）に満たない場合の例外."""


def _extract_rmse(row: Mapping[str, object]) -> float | None:
    """model_registryの`val_metrics`（JSON文字列）からrmseを取り出す。取得できなければNone."""
    raw_metrics = row.get("val_metrics")
    try:
        metrics = json.loads(raw_metrics) if isinstance(raw_metrics, str) else (raw_metrics or {})
    except json.JSONDecodeError:
        return None
    if not isinstance(metrics, dict):
        return None
    rmse = metrics.get("rmse")
    # RMSEは定義上0以上。負値や破損値を「取得できた」として扱うと重みが異常発散しうるため、
    # そうした値は「取得できなかった」（＝等重みフォールバック）として扱う
    return float(rmse) if isinstance(rmse, int | float) and not isinstance(rmse, bool) and rmse >= 0 else None


def predict_ensemble_sync(
    model_rows: Mapping[str, Mapping[str, object]],
    df: pd.DataFrame,
    forecast_horizon: int,
    get_predictor: Callable[[str], PredictorProtocol],
) -> tuple[PredictionOutput, list[str]]:
    """事前取得済みの champion 行から、銘柄別モデル群の予測をRMSE逆数で重み付け平均する.

    `model_rows` は `{model_type: model_registry_db.get_model(...)の戻り値}`
    （呼び出し側が `model_champions` の `lane=f"{model_type}:{ticker}"` から
    champion version を引き、`get_model` で行を取得しておく）。

    RMSEが取得できないモデル（旧形式保存等）は重み1.0（他モデルと同等）にフォールバックする。
    個々のモデルのロード/推論が失敗した場合はそのモデルをスキップし、残りで続行する
    （「1件の失敗で全体を止めない」方針）。

    信頼区間（confidence_lower/upper）も各モデルの区間を同じ重みで平均するのみで、
    モデル間の予測値の乖離（不一致）そのものを分散として合成しているわけではない。
    そのため実際の不確実性より狭い区間になりうる近似値である点に注意。
    """
    predictions: list[PredictionOutput] = []
    weights: list[float] = []
    component_models: list[str] = []

    for model_type, row in model_rows.items():
        try:
            artifact_path = row.get("artifact_path")
            if not artifact_path:
                continue
            predictor = get_predictor(model_type)
            predictor.load(str(artifact_path))
            output = predictor.predict(df, forecast_horizon=forecast_horizon)
        except Exception:
            logger.exception("アンサンブル構成モデルの予測に失敗: %s", model_type)
            continue

        rmse = _extract_rmse(row)
        weight = 1.0 / max(rmse, _MIN_RMSE_FOR_WEIGHTING) if rmse is not None else 1.0

        predictions.append(output)
        weights.append(weight)
        component_models.append(model_type)

    return _combine_weighted(predictions, weights, component_models)


def _combine_weighted(
    predictions: list[PredictionOutput], weights: list[float], component_models: list[str]
) -> tuple[PredictionOutput, list[str]]:
    """モデル数チェック・重みクリップ・加重平均を行う."""
    if len(predictions) < MIN_COMPONENT_MODELS:
        raise InsufficientModelsError(
            f"アンサンブル予測には{MIN_COMPONENT_MODELS}種類以上の学習済みモデルが必要です"
            f"（現在利用可能: {len(predictions)}種類）"
        )

    # 最小重みの_MAX_WEIGHT_RATIO倍を上限にクリップし、1モデルへの実質的な収束を防ぐ。
    weight_cap = min(weights) * _MAX_WEIGHT_RATIO
    weights = [min(w, weight_cap) for w in weights]

    total_weight = sum(weights)
    normalized_weights = [w / total_weight for w in weights]
    paired = list(zip(predictions, normalized_weights, strict=True))

    # 各モデルの残差を独立とみなし、分散加法性 Var(Σ w_i X_i) = Σ w_i^2 Var(X_i) で
    # 合成標準偏差を求める。1つでもresidual_std欠損（旧形式モデル）があれば
    # 合成できないためNoneにフォールバックする。
    residual_stds = [p["residual_std"] for p, _ in paired]
    combined_residual_std: float | None
    if all(s is not None for s in residual_stds):
        # mypyはall()内のNone判定だけでは要素型を絞り込めないため、明示的にlist[float]へ絞る
        non_none_stds: list[float] = [s for s in residual_stds if s is not None]
        combined_residual_std = math.sqrt(sum((w * s) ** 2 for (_, w), s in zip(paired, non_none_stds, strict=True)))
    else:
        combined_residual_std = None

    result: PredictionOutput = {
        "target_date": "TBD",
        "predicted_close": sum(p["predicted_close"] * w for p, w in paired),
        "prediction_rate": sum(p["prediction_rate"] * w for p, w in paired),
        "confidence_lower": sum(p["confidence_lower"] * w for p, w in paired),
        "confidence_upper": sum(p["confidence_upper"] * w for p, w in paired),
        "residual_std": combined_residual_std,
    }
    return result, component_models
