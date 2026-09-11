"""モデルレジストリ関連 API（P5 時点は PSI ドリフトのみ）.

`plans/03_システム設計` §2.4。`champions` / `promotions` は `model_registry` に実モデルが
登録され始める後続フェーズ（ML predictor スタック導入時）で追加する。ドリフト監視は
`prediction_ledger.feature_snapshot` だけで動くため先行して提供する。
"""

from __future__ import annotations

from fastapi import APIRouter, Query

from backend.models.common import ApiResponse
from backend.services.db.drift_db import list_drift_snapshots

router = APIRouter(prefix="/api/registry", tags=["registry"])


@router.get("/drift", response_model=ApiResponse[list[dict]], summary="PSI ドリフト履歴")
async def drift(
    feature: str | None = Query(default=None, description="feature_snapshot の dotted path"),
    limit: int = Query(default=200, ge=1, le=1000),
) -> ApiResponse[list[dict]]:
    """特徴量分布ドリフト（PSI）の履歴を古い順で返す（モデルラボの推移グラフ用）."""
    return ApiResponse.ok(await list_drift_snapshots(feature_name=feature, limit=limit))
