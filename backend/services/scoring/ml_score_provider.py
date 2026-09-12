"""断面プールモデル（P5d）+ 銘柄別モデル（P9）を `recommender.MlScoreProvider` として配線する.

Market Lens `backend/services/recommender.py` の `_compute_pool_ml_score`/`_compute_ml_score`
に相当（🔧）。断面プールモデルは champion 未登録・universe 外・推論失敗はすべて
`(None, None)` を返し、銘柄別アンサンブルも同様に champion 不足（2種未満）・推論失敗は
`(None, None)` を返す。`combine_ml_score_providers` で両者を並列合成し、どちらか一方が
欠けても残りだけで動作する（ユーザー確認済み、`plans/04_タスクリスト.md` P9）。

`PanelContext`（断面特徴量、1日1回構築）と champion `PoolClassifier` は呼び出し側
（`services/picks/pipeline.run_picks`）が1回だけ用意し、銘柄別アンサンブルの champion 行
（`fetch_per_ticker_champion_rows`）は銘柄ごとに都度取得する。
"""

from __future__ import annotations

import logging
import math
from collections.abc import Callable, Mapping

import pandas as pd

from backend.config import settings
from backend.services.db import model_registry_db
from backend.services.learning import ensemble_predictor
from backend.services.learning.panel_feature_service import PanelContext, build_inference_row
from backend.services.learning.per_ticker_training_service import FORECAST_HORIZON_DAYS, get_predictor
from backend.services.learning.pool_model import POOL_LANE
from backend.services.learning.pool_training_service import PoolClassifier, load_pool_classifier

logger = logging.getLogger(__name__)

MlScoreProvider = Callable[[pd.DataFrame, str], tuple[float | None, float | None]]


async def load_champion_pool_classifier() -> PoolClassifier | None:
    """lane="ml_pool" の現行 champion をロードする（champion 未登録・ロード失敗は None）."""
    version = await model_registry_db.get_champion(POOL_LANE)
    if version is None:
        return None
    try:
        return await load_pool_classifier(version)
    except (ValueError, FileNotFoundError) as e:
        logger.warning("プールモデル champion のロードに失敗: %s (%s)", version, e)
        return None


def make_pool_ml_score_provider(ctx: PanelContext, clf: PoolClassifier | None) -> MlScoreProvider:
    """事前構築済み `PanelContext` と champion モデルを閉じ込めた `MlScoreProvider` を返す.

    「当日 universe で前方 H 日リターンが上位 `POOL_TOP_FRACTION` に入る確率」をそのまま
    `score = proba * 100` として ML ファクターへ渡す（回帰の tanh z 変換はここでは不要 —
    分類器の確率は既に 0-100 スケールへ素直に写せるため）。`prediction_rate` フィールドには
    その確率自体（0.0-1.0）を入れる。`clf=None` や universe 外の銘柄は ML ファクターを
    合成に入れない（`(None, None)`）。
    """

    def _provider(_df: pd.DataFrame, ticker: str) -> tuple[float | None, float | None]:
        if clf is None or not ctx.has(ticker):
            return None, None
        row = build_inference_row(ticker, ctx, ticker_te_map=clf.ticker_te_map)
        if row is None:
            return None, None
        try:
            proba = float(clf.predict_proba(row)[0])
        except Exception:  # noqa: BLE001 - 推論失敗時は ML ファクターなしにフォールバック（合成は止めない）
            logger.debug("プールモデル推論に失敗: %s", ticker, exc_info=True)
            return None, None
        score = max(0.0, min(100.0, proba * 100.0))
        return score, proba

    return _provider


def _ensemble_model_types() -> tuple[str, ...]:
    """銘柄別アンサンブルに含めるモデルタイプ.

    既定は xgboost + random_forest の2種のみ。LSTM/Transformer は torch 同期推論で
    銘柄あたり数百msかかり、ピック生成のバッチ処理（候補プール全体を都度スコアリング）では
    所要時間が成立しないため、`settings.recommender_ensemble_include_dl`（既定 False）で
    opt-in する場合のみ含める（Market Lens `recommender._ensemble_model_types` と同じ理由）。
    """
    if settings.recommender_ensemble_include_dl:
        return ensemble_predictor.PER_TICKER_MODEL_TYPES
    return ("xgboost", "random_forest")


async def fetch_per_ticker_champion_rows(ticker: str) -> dict[str, dict[str, object]]:
    """有効なモデルタイプ（`_ensemble_model_types`）それぞれについて、指定銘柄の現行 champion
    行（`model_registry_db.get_model` の戻り値）を取得する（champion 未設定のタイプは省略）.
    """
    rows: dict[str, dict[str, object]] = {}
    for model_type in _ensemble_model_types():
        version = await model_registry_db.get_champion(f"{model_type}:{ticker}")
        if version is None:
            continue
        row = await model_registry_db.get_model(version)
        if row is not None:
            rows[model_type] = row
    return rows


def _prediction_rate_to_score(prediction_rate: float, residual_std: float | None) -> float:
    """予測変化率を0〜100スコアに変換する（Market Lens `recommender._prediction_rate_to_score` を移植）.

    held-out 検証残差の標準偏差（residual_std）が使えるモデルでは、それに対する z 値を
    tanh で±1へ押し込むことで「そのモデル・その銘柄の予測誤差スケールに対して予測変化率が
    どれだけ大きいか」を反映したスケーリングにする。residual_std が無い（旧形式）場合や
    ゼロ近傍で発散しうる場合は±5%を満点/最低点とする固定線形式にフォールバックする。
    """
    if residual_std is not None and residual_std > 1e-6:
        z = prediction_rate / residual_std
        score = 50.0 + 50.0 * math.tanh(z)
    else:
        capped = max(-0.05, min(0.05, prediction_rate))
        score = 50.0 + (capped / 0.05) * 50.0
    return max(0.0, min(100.0, score))


def make_per_ticker_ensemble_provider(model_rows: Mapping[str, Mapping[str, object]]) -> MlScoreProvider:
    """事前取得済みの champion 行（`fetch_per_ticker_champion_rows`）から、銘柄別アンサンブル
    予測を ML ファクターへ変換する `MlScoreProvider` を返す.

    `ensemble_predictor.predict_ensemble_sync` は同期関数であり非同期 DB I/O を行わないため、
    `model_rows` は呼び出し側が銘柄ごとに事前取得したものを渡す（`make_pool_ml_score_provider`
    と同じ理由）。2種類未満しか champion が揃っていない場合は ML ファクターを合成に
    入れない（`(None, None)`）。
    """

    def _provider(df: pd.DataFrame, _ticker: str) -> tuple[float | None, float | None]:
        if len(model_rows) < ensemble_predictor.MIN_COMPONENT_MODELS:
            return None, None
        try:
            output, _components = ensemble_predictor.predict_ensemble_sync(
                model_rows, df, FORECAST_HORIZON_DAYS, get_predictor
            )
        except ensemble_predictor.InsufficientModelsError:
            return None, None
        except Exception:  # noqa: BLE001 - 推論失敗時は ML ファクターなしにフォールバック（合成は止めない）
            logger.debug("銘柄別アンサンブル推論に失敗", exc_info=True)
            return None, None
        rate = output["prediction_rate"]
        score = _prediction_rate_to_score(rate, output["residual_std"])
        return score, rate

    return _provider


def combine_ml_score_providers(pool_provider: MlScoreProvider, ticker_provider: MlScoreProvider) -> MlScoreProvider:
    """断面プールモデルと銘柄別アンサンブルの ML ファクターを並列合成する（P9）.

    ドメインも出力も異なる別系統のモデルであり、どちらか一方が欠けても残りだけで
    動作する必要がある（ユーザー確認済み）。
    - 両方 `(None, None)` → `(None, None)`。
    - 片方のみ利用可能 → そのまま採用。
    - 両方利用可能 → score は 0-100 の比較可能なスケールのため単純平均する。
      prediction_rate は両モデルで意味が異なる（プールは「上位 `POOL_TOP_FRACTION` に入る
      確率」、銘柄別アンサンブルは「forecast_horizon 日先の変化率」）ため平均せず、
      `recommender._build_reasoning` の表示テキスト（「N 日後に X% 上昇/下落と予測」）の
      意味に一致する銘柄別アンサンブル側を優先する。
    """

    def _provider(df: pd.DataFrame, ticker: str) -> tuple[float | None, float | None]:
        pool_score, pool_rate = pool_provider(df, ticker)
        ticker_score, ticker_rate = ticker_provider(df, ticker)

        scores = [s for s in (pool_score, ticker_score) if s is not None]
        if not scores:
            return None, None
        combined_score = sum(scores) / len(scores)
        rate = ticker_rate if ticker_rate is not None else pool_rate
        return combined_score, rate

    return _provider
