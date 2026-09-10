"""trend_snapshots テーブルの読み書き（SQLAlchemy async）.

Market Lens は raw sqlite の `database.py` に `insert_trend_snapshot` /
`get_latest_trend_snapshot` を持つが、Alpha Forge は SQLAlchemy async に統一しているため
ここへ切り出す。`trends` は JSON 文字列（list[Trend] の dump）で保存する。
"""

from __future__ import annotations

import json
from datetime import datetime

from sqlalchemy import text

from backend.services.db.database import get_db
from backend.services.jst_time import JST

_INSERT = text(
    """
    INSERT OR REPLACE INTO trend_snapshots (
        snapshot_at, status, model, trends, signal_count, source_summary, created_at
    ) VALUES (
        :snapshot_at, :status, :model, :trends, :signal_count, :source_summary, :created_at
    )
    """
)

_LATEST = text("SELECT * FROM trend_snapshots ORDER BY snapshot_at DESC LIMIT 1")


async def insert_trend_snapshot(
    *,
    snapshot_at: str,
    status: str,
    model: str,
    trends: list[dict[str, object]],
    signal_count: int,
    source_summary: str,
) -> None:
    """トレンドスナップショットを 1 行 upsert する."""
    async with get_db() as db:
        await db.execute(
            _INSERT,
            {
                "snapshot_at": snapshot_at,
                "status": status,
                "model": model,
                "trends": json.dumps(trends, ensure_ascii=False),
                "signal_count": signal_count,
                "source_summary": source_summary,
                "created_at": datetime.now(JST).isoformat(timespec="seconds"),
            },
        )


async def get_latest_trend_snapshot() -> dict[str, object] | None:
    """最新のトレンドスナップショット行を返す（無ければ None）."""
    async with get_db() as db:
        row = (await db.execute(_LATEST)).first()
        return dict(row._mapping) if row is not None else None
