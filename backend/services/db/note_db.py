"""`daily_notes` の読み書き（SQLAlchemy async）.

`note_date` が一意キー（1 日 1 件）。`eod_review_db.py` と同じ upsert パターンを踏襲する。
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime

from sqlalchemy import text

from backend.services.db.database import get_db
from backend.services.jst_time import JST


async def get_note_by_date(note_date: str) -> dict[str, object] | None:
    """指定日の 1 件を返す（無ければ None）."""
    async with get_db() as db:
        result = await db.execute(
            text("SELECT * FROM daily_notes WHERE note_date = :note_date"), {"note_date": note_date}
        )
        row = result.first()
        return dict(row._mapping) if row is not None else None


async def get_note_by_id(note_id: str) -> dict[str, object] | None:
    """`note_id` で 1 件を返す（無ければ None）."""
    async with get_db() as db:
        result = await db.execute(text("SELECT * FROM daily_notes WHERE note_id = :note_id"), {"note_id": note_id})
        row = result.first()
        return dict(row._mapping) if row is not None else None


async def upsert_note(
    *,
    note_date: str,
    title: str,
    body_markdown: str,
    source_pick_ids: list[str],
    model_version: str,
    has_price_mention_warning: bool,
) -> dict[str, object]:
    """指定日のドラフトを作成、または再生成として上書きする（常に `status="draft"` に戻す）.

    `note_date` が既存なら `ON CONFLICT` で上書きし、承認・投稿の記録（approved_at 等）は
    クリアする（再生成＝作り直しのため）。`note_id` は初回作成時のみ新規発行され、
    再生成では既存行のものがそのまま維持される（フロント側で ID が変わらないようにするため）。
    """
    note_id = str(uuid.uuid4())
    generated_at = datetime.now(JST).isoformat(timespec="seconds")
    async with get_db() as db:
        await db.execute(
            text("""
                INSERT INTO daily_notes (
                    note_id, note_date, title, body_markdown, status, source_pick_ids,
                    model_version, has_price_mention_warning, generated_at,
                    approved_at, published_at, published_url
                ) VALUES (
                    :note_id, :note_date, :title, :body_markdown, 'draft', :source_pick_ids,
                    :model_version, :has_price_mention_warning, :generated_at,
                    NULL, NULL, NULL
                )
                ON CONFLICT(note_date) DO UPDATE SET
                    title = excluded.title,
                    body_markdown = excluded.body_markdown,
                    status = 'draft',
                    source_pick_ids = excluded.source_pick_ids,
                    model_version = excluded.model_version,
                    has_price_mention_warning = excluded.has_price_mention_warning,
                    generated_at = excluded.generated_at,
                    approved_at = NULL,
                    published_at = NULL,
                    published_url = NULL
                """),
            {
                "note_id": note_id,
                "note_date": note_date,
                "title": title,
                "body_markdown": body_markdown,
                "source_pick_ids": json.dumps(source_pick_ids, ensure_ascii=False),
                "model_version": model_version,
                "has_price_mention_warning": has_price_mention_warning,
                "generated_at": generated_at,
            },
        )
    found = await get_note_by_date(note_date)
    assert found is not None  # noqa: S101 — 直後の自己 upsert 結果を読むだけなので必ず存在する  # nosec B101
    return found


async def update_note_content(note_id: str, *, title: str, body_markdown: str) -> dict[str, object] | None:
    """本文を手直しする（`status` は変えない）。対象行が無ければ None."""
    async with get_db() as db:
        result = await db.execute(
            text("UPDATE daily_notes SET title = :title, body_markdown = :body_markdown WHERE note_id = :note_id"),
            {"title": title, "body_markdown": body_markdown, "note_id": note_id},
        )
        if result.rowcount == 0:
            return None
    return await get_note_by_id(note_id)


async def update_note_status(
    note_id: str,
    *,
    status: str,
    approved_at: str | None = None,
    published_at: str | None = None,
    published_url: str | None = None,
) -> dict[str, object] | None:
    """状態遷移（approve/reject/mark-published）を反映する。対象行が無ければ None."""
    async with get_db() as db:
        result = await db.execute(
            text("""
                UPDATE daily_notes
                SET status = :status,
                    approved_at = COALESCE(:approved_at, approved_at),
                    published_at = COALESCE(:published_at, published_at),
                    published_url = COALESCE(:published_url, published_url)
                WHERE note_id = :note_id
                """),
            {
                "status": status,
                "approved_at": approved_at,
                "published_at": published_at,
                "published_url": published_url,
                "note_id": note_id,
            },
        )
        if result.rowcount == 0:
            return None
    return await get_note_by_id(note_id)


async def list_recent_notes(*, limit: int = 30) -> list[dict[str, object]]:
    """直近 N 件を新しい順で返す."""
    async with get_db() as db:
        result = await db.execute(
            text("SELECT * FROM daily_notes ORDER BY note_date DESC LIMIT :limit"), {"limit": limit}
        )
        return [dict(r._mapping) for r in result]
