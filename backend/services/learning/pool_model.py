"""断面プール型モデル（P5d）の識別子.

Market Lens `backend/services/pool_model.py` から移植（変更なし）。プールモデルは
「全ユニバース断面で1モデル」であり、`model_registry` には他のレーン（`recommender_llm_<lane>`）
とは**別の識別子**で保存する:

- `model_type = POOL_MODEL_TYPE`（`"xgboost_pool"`）
- `model_registry_db.upsert_model` の `ticker` 既定値 `POOL_TICKER_SENTINEL`（`"__pool__"`）と一致
"""

from __future__ import annotations

from typing import Final

# 断面プールモデルの model_registry.model_type。既存の recommender_llm_<lane> とは
# 意図的に別文字列にする（`services/registry/model_registry.model_type_for_lane` 参照）。
POOL_MODEL_TYPE: Final[str] = "xgboost_pool"

# 断面プールモデルの model_registry.ticker。1モデルなので銘柄コードを持たず番兵値を使う。
POOL_TICKER_SENTINEL: Final[str] = "__pool__"

# champion/challenger（`model_champions`/`model_promotions`）上でのプールモデル専用レーン名。
POOL_LANE: Final[str] = "ml_pool"
