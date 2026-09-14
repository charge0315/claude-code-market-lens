"""`eval_snapshots` / `calibration_curves` の読み書き（SQLAlchemy async）.

`plans/03_システム設計` §1.3。評価指標は時系列で保持し、成長曲線にする（CL-3）。
`calibration_curves` は較正曲線の点列を JSON で保持し、UI で「予測 X% → 実測 Y%」を出す。
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime

from sqlalchemy import text

from backend.services.db.database import get_db
from backend.services.jst_time import JST


async def insert_eval_snapshot(
    *,
    scope: str,
    metric_name: str,
    metric_value: float,
    sample_n: int,
    model_version: str | None = None,
    horizon_days: int | None = None,
    confidence_bucket: str | None = None,
    computed_at: str | None = None,
) -> None:
    """評価指標を 1 行追加する（同一指標の時系列は追記で成長曲線にする）."""
    async with get_db() as db:
        await db.execute(
            text("""
                INSERT INTO eval_snapshots (
                    snapshot_id, computed_at, scope, model_version, metric_name,
                    metric_value, sample_n, horizon_days, confidence_bucket
                ) VALUES (
                    :snapshot_id, :computed_at, :scope, :model_version, :metric_name,
                    :metric_value, :sample_n, :horizon_days, :confidence_bucket
                )
                """),
            {
                "snapshot_id": str(uuid.uuid4()),
                "computed_at": computed_at or datetime.now(JST).isoformat(timespec="seconds"),
                "scope": scope,
                "model_version": model_version,
                "metric_name": metric_name,
                "metric_value": metric_value,
                "sample_n": sample_n,
                "horizon_days": horizon_days,
                "confidence_bucket": confidence_bucket,
            },
        )


async def list_eval_snapshots(
    *, scope: str | None = None, metric_name: str | None = None, limit: int = 500
) -> list[dict[str, object]]:
    """評価指標の時系列を古い順に返す（成長曲線の描画用）."""
    clauses: list[str] = []
    params: dict[str, object] = {"limit": limit}
    if scope is not None:
        clauses.append("scope = :scope")
        params["scope"] = scope
    if metric_name is not None:
        clauses.append("metric_name = :metric_name")
        params["metric_name"] = metric_name
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    async with get_db() as db:
        result = await db.execute(
            text(
                f"SELECT * FROM eval_snapshots {where} ORDER BY computed_at ASC LIMIT :limit"  # noqa: S608  # nosec B608 - where は定数のみ
            ),
            params,
        )
        return [dict(r._mapping) for r in result]


async def upsert_calibration_curve(
    *,
    scope: str,
    points: list[dict[str, float]],
    brier: float | None,
    is_calibrated: bool,
    horizon_days: int | None = None,
    direction: str | None = None,
    computed_at: str | None = None,
) -> None:
    """較正曲線を 1 行追加する（同一 scope の時系列は追記）."""
    async with get_db() as db:
        await db.execute(
            text("""
                INSERT INTO calibration_curves (
                    curve_id, computed_at, scope, horizon_days, direction, points, brier, is_calibrated
                ) VALUES (
                    :curve_id, :computed_at, :scope, :horizon_days, :direction, :points, :brier, :is_calibrated
                )
                """),
            {
                "curve_id": str(uuid.uuid4()),
                "computed_at": computed_at or datetime.now(JST).isoformat(timespec="seconds"),
                "scope": scope,
                "horizon_days": horizon_days,
                "direction": direction,
                "points": json.dumps(points, ensure_ascii=False),
                "brier": brier,
                "is_calibrated": 1 if is_calibrated else 0,
            },
        )


async def get_latest_calibration_curve(*, scope: str, horizon_days: int | None = None) -> dict[str, object] | None:
    """指定 scope の最新較正曲線を返す（`points` は復元済み）."""
    clause = "AND horizon_days = :hd" if horizon_days is not None else ""
    params: dict[str, object] = {"scope": scope}
    if horizon_days is not None:
        params["hd"] = horizon_days
    async with get_db() as db:
        row = (
            await db.execute(
                text(
                    f"SELECT * FROM calibration_curves WHERE scope = :scope {clause} "  # noqa: S608  # nosec B608 - clause は定数のみ
                    "ORDER BY computed_at DESC LIMIT 1"
                ),
                params,
            )
        ).first()
        if row is None:
            return None
        raw = dict(row._mapping)
        raw["points"] = json.loads(str(raw.get("points") or "[]"))
        return raw
