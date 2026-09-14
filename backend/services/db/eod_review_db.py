"""`eod_reviews` の読み書き（SQLAlchemy async）.

`review_date` が PK のため 1 日 1 件。`force` 再生成時は `ON CONFLICT` で上書きする
（Market Lens は delete→insert だが、Alpha Forge のスキーマは列が少なく upsert で足りる）。
"""

from __future__ import annotations

import json
from datetime import datetime

from sqlalchemy import text

from backend.services.db.database import get_db
from backend.services.jst_time import JST


async def get_eod_review(review_date: str) -> dict[str, object] | None:
    """1 日分を返す（無ければ None）."""
    async with get_db() as db:
        result = await db.execute(
            text("SELECT * FROM eod_reviews WHERE review_date = :review_date"), {"review_date": review_date}
        )
        row = result.first()
        return dict(row._mapping) if row is not None else None


async def upsert_eod_review(
    *, review_date: str, summary: str, learned_heuristics: list[dict[str, object]], created_at: str | None = None
) -> None:
    """1 日分を作成または上書きする（`force` 再生成用）."""
    async with get_db() as db:
        await db.execute(
            text("""
                INSERT INTO eod_reviews (review_date, summary, learned_heuristics, created_at)
                VALUES (:review_date, :summary, :learned_heuristics, :created_at)
                ON CONFLICT(review_date) DO UPDATE SET
                    summary = excluded.summary,
                    learned_heuristics = excluded.learned_heuristics,
                    created_at = excluded.created_at
                """),
            {
                "review_date": review_date,
                "summary": summary,
                "learned_heuristics": json.dumps(learned_heuristics, ensure_ascii=False),
                "created_at": created_at or datetime.now(JST).isoformat(timespec="seconds"),
            },
        )


async def list_recent_eod_reviews(*, limit: int = 5) -> list[dict[str, object]]:
    """直近 N 件を新しい順で返す."""
    async with get_db() as db:
        result = await db.execute(
            text("SELECT * FROM eod_reviews ORDER BY review_date DESC LIMIT :limit"), {"limit": limit}
        )
        return [dict(r._mapping) for r in result]
