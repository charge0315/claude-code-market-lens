"""`drift_snapshots` テーブルの読み書き（SQLAlchemy async）.

`plans/03_システム設計` §1.5（N5）。特徴量分布ドリフト（PSI）の履歴を時系列で保持する。
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import text

from backend.services.db.database import get_db
from backend.services.jst_time import JST


async def insert_drift_snapshot(
    *,
    feature_name: str,
    psi: float,
    baseline_window: str,
    current_window: str,
    drift_flag: bool,
    triggered_retrain: bool = False,
    computed_at: str | None = None,
) -> None:
    """1 特徴量分の PSI 計測結果を追加する."""
    async with get_db() as db:
        await db.execute(
            text("""
                INSERT INTO drift_snapshots (
                    drift_id, computed_at, feature_name, psi, baseline_window, current_window,
                    drift_flag, triggered_retrain
                ) VALUES (
                    :drift_id, :computed_at, :feature_name, :psi, :baseline_window, :current_window,
                    :drift_flag, :triggered_retrain
                )
                """),
            {
                "drift_id": str(uuid.uuid4()),
                "computed_at": computed_at or datetime.now(JST).isoformat(timespec="seconds"),
                "feature_name": feature_name,
                "psi": psi,
                "baseline_window": baseline_window,
                "current_window": current_window,
                "drift_flag": 1 if drift_flag else 0,
                "triggered_retrain": 1 if triggered_retrain else 0,
            },
        )


async def list_drift_snapshots(*, feature_name: str | None = None, limit: int = 200) -> list[dict[str, object]]:
    """PSI ドリフトの履歴を古い順に返す（UI のドリフト推移グラフ用）."""
    clause = "WHERE feature_name = :feature_name" if feature_name else ""
    params: dict[str, object] = {"limit": limit}
    if feature_name:
        params["feature_name"] = feature_name
    async with get_db() as db:
        result = await db.execute(
            text(
                f"SELECT * FROM drift_snapshots {clause} ORDER BY computed_at ASC LIMIT :limit"  # noqa: S608  # nosec B608 - clause は定数のみ
            ),
            params,
        )
        return [dict(r._mapping) for r in result]
