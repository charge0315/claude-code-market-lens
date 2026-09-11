"""モデルレジストリ — 登録と champion の初回ブートストラップ（N1）.

`plans/03_システム設計` §1.4。Alpha Forge の「モデル」は P5d（xgboost 等の実 ML）まで
`services/picks/pipeline.MODEL_VERSION`（recommender + LLM プロンプトの構成スナップショット）
を指す。系統（lane = `mid_term` / `short_term`。将来 `mid_term_pool` 等が増えても対応）ごとに
`model_type = "recommender_llm_<lane>"` として `model_registry` へ符号化する
（既存テーブルへの列追加なしで lane を表現するため）。

初回（その lane にまだ champion が無い）は昇格ゲートを経由せず自動で champion にする
（`promoted_by="bootstrap"`）。2 本目以降のバージョンは `services/registry/promotion` の
昇格ゲートを通さない限り champion にはならない。
"""

from __future__ import annotations

import logging

from backend.services.db import model_registry_db

logger = logging.getLogger(__name__)


def model_type_for_lane(lane: str) -> str:
    """lane を `model_registry.model_type` へ符号化する."""
    return f"recommender_llm_{lane}"


async def ensure_registered(
    version: str,
    *,
    lane: str,
    val_metrics: dict[str, object] | None = None,
    feature_list: list[str] | None = None,
) -> None:
    """バージョンが未登録なら `model_registry` へ追加する（既存なら val_metrics のみ更新）."""
    await model_registry_db.upsert_model(
        version=version,
        model_type=model_type_for_lane(lane),
        val_metrics=val_metrics,
        feature_list=feature_list or ["technical", "trend", "fundamental", "sentiment"],
    )


async def bootstrap_champion_if_missing(lane: str, version: str) -> bool:
    """lane に champion が無ければ、指定バージョンを無条件で champion にする.

    昇格ゲート（`promotion.evaluate_promotion`）を経由しない唯一の champion 設定経路。
    2 本目以降のバージョンをここで champion にすることはない（既に champion がいれば no-op）。
    """
    existing = await model_registry_db.get_champion(lane)
    if existing is not None:
        return False
    await model_registry_db.set_champion(lane, version, promoted_by="bootstrap")
    logger.info("モデルレジストリ: lane=%s の champion を初回登録しました（%s）", lane, version)
    return True
