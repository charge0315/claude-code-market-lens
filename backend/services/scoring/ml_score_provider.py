"""断面プールモデル（P5d）を `recommender.MlScoreProvider` として配線する.

Market Lens `backend/services/recommender.py` の `_compute_pool_ml_score` に相当（🔧）。
Market Lens は `POOL_MODEL_ENABLED` フラグと per-ticker ローテーションへのフォールバックを
持つが、Alpha Forge は per-ticker ローテーションを移植しない方針（`plans/04_タスクリスト.md`
P5d）のため、champion 未登録・universe 外・推論失敗はすべて `(None, None)` を返し
recommender が ML ファクターなしで残り3ファクターを再正規化するだけで良い（フラグ不要）。

`PanelContext`（断面特徴量、1日1回構築）と champion `PoolClassifier` は呼び出し側
（`services/picks/pipeline.run_picks`）が1回だけ用意し、`make_pool_ml_score_provider` で
閉じ込めた同期 provider を `compute_recommendation(..., ml_score_provider=...)` へ渡す。
"""

from __future__ import annotations

import logging
from collections.abc import Callable

import pandas as pd

from backend.services.db import model_registry_db
from backend.services.learning.panel_feature_service import PanelContext, build_inference_row
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
