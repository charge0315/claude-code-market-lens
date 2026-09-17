"""日次noteドラフトのオーケストレーション（🆕）.

生成→レビュー→承認/却下→（人間が手動でnote.comへ投稿）→投稿完了記録、という状態遷移を
`daily_notes` テーブル上で管理する。実際の note.com への投稿は公式APIが無いため人間が行う
（`models/note.py` docstring 参照）。
"""

from __future__ import annotations

import json
from datetime import datetime

from backend.models.note import DailyNote
from backend.services.db import note_db
from backend.services.jst_time import JST, today_jst
from backend.services.ledger import prediction_ledger as pl
from backend.services.notes.note_generator import generate, has_price_mention


def _note_from_row(row: dict[str, object]) -> DailyNote:
    return DailyNote(
        note_id=str(row["note_id"]),
        note_date=str(row["note_date"]),
        title=str(row["title"]),
        body_markdown=str(row["body_markdown"]),
        status=row["status"],
        source_pick_ids=list(json.loads(str(row["source_pick_ids"]))),
        model_version=str(row["model_version"]),
        has_price_mention_warning=bool(row["has_price_mention_warning"]),
        generated_at=str(row["generated_at"]),
        approved_at=str(row["approved_at"]) if row.get("approved_at") else None,
        published_at=str(row["published_at"]) if row.get("published_at") else None,
        published_url=str(row["published_url"]) if row.get("published_url") else None,
    )


async def _generate_for_date(note_date: str, *, force: bool) -> DailyNote:
    if not force:
        existing = await note_db.get_note_by_date(note_date)
        if existing is not None:
            return _note_from_row(existing)

    mid_term = await pl.list_picks(horizon_type="mid_term", issued_from=f"{note_date}T00:00:00", limit=50)
    short_term = await pl.list_picks(horizon_type="short_term", issued_from=f"{note_date}T00:00:00", limit=50)
    title, body, model_version = await generate(note_date, mid_term, short_term)
    source_pick_ids = [p.pick_id for p in (*mid_term, *short_term)]

    row = await note_db.upsert_note(
        note_date=note_date,
        title=title,
        body_markdown=body,
        source_pick_ids=source_pick_ids,
        model_version=model_version,
        has_price_mention_warning=has_price_mention(body),
    )
    return _note_from_row(row)


async def generate_today(*, force: bool = False) -> DailyNote:
    """本日分のドラフトを生成する（既にあれば再利用、`force=True` で再生成）."""
    return await _generate_for_date(today_jst(), force=force)


async def get_today() -> DailyNote | None:
    """本日分のドラフトを返す（無ければ None、まだ生成タスクが走っていない場合等）."""
    row = await note_db.get_note_by_date(today_jst())
    return _note_from_row(row) if row is not None else None


async def list_recent(*, limit: int = 30) -> list[DailyNote]:
    """直近 N 件を新しい順で返す."""
    rows = await note_db.list_recent_notes(limit=limit)
    return [_note_from_row(r) for r in rows]


async def update_content(note_id: str, *, title: str, body_markdown: str) -> DailyNote | None:
    """本文を手直しする（人間のレビュー編集）。対象が無ければ None."""
    row = await note_db.update_note_content(note_id, title=title, body_markdown=body_markdown)
    return _note_from_row(row) if row is not None else None


async def approve(note_id: str) -> DailyNote | None:
    """承認する（note.comへの投稿はこの後、人間が手動で行う）."""
    now = datetime.now(JST).isoformat(timespec="seconds")
    row = await note_db.update_note_status(note_id, status="approved", approved_at=now)
    return _note_from_row(row) if row is not None else None


async def reject(note_id: str) -> DailyNote | None:
    """却下する（配信しない）."""
    row = await note_db.update_note_status(note_id, status="rejected")
    return _note_from_row(row) if row is not None else None


async def regenerate(note_id: str) -> DailyNote | None:
    """既存ドラフトを破棄し、同じ日付で再生成する（対象の `note_date` を使う。当日とは限らない）."""
    existing = await note_db.get_note_by_id(note_id)
    if existing is None:
        return None
    return await _generate_for_date(str(existing["note_date"]), force=True)


async def mark_published(note_id: str, *, published_url: str) -> DailyNote | None:
    """人間が note.com へ投稿完了した後、URLを記録する."""
    now = datetime.now(JST).isoformat(timespec="seconds")
    row = await note_db.update_note_status(note_id, status="published", published_at=now, published_url=published_url)
    return _note_from_row(row) if row is not None else None
