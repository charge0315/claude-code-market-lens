"""`services/db/note_db` の検証（upsert が note_id を維持しつつ状態をリセットすること）."""

from __future__ import annotations

from pathlib import Path

from backend.services.db import note_db


async def test_upsert_note_creates_new_row(migrated_db: Path) -> None:
    row = await note_db.upsert_note(
        note_date="2026-09-17",
        title="タイトル",
        body_markdown="本文",
        source_pick_ids=["p1", "p2"],
        model_version="anthropic:test",
        has_price_mention_warning=False,
    )

    assert row["note_date"] == "2026-09-17"
    assert row["status"] == "draft"


async def test_upsert_note_on_conflict_keeps_note_id_and_resets_status(migrated_db: Path) -> None:
    first = await note_db.upsert_note(
        note_date="2026-09-17",
        title="1回目",
        body_markdown="本文1",
        source_pick_ids=["p1"],
        model_version="anthropic:test",
        has_price_mention_warning=False,
    )
    await note_db.update_note_status(str(first["note_id"]), status="approved", approved_at="2026-09-17T09:00:00+09:00")

    second = await note_db.upsert_note(
        note_date="2026-09-17",
        title="2回目（再生成）",
        body_markdown="本文2",
        source_pick_ids=["p2"],
        model_version="anthropic:test",
        has_price_mention_warning=True,
    )

    # note_id は維持される（フロントの参照が壊れないように）。
    assert second["note_id"] == first["note_id"]
    assert second["title"] == "2回目（再生成）"
    # 再生成なので承認/投稿記録はリセットされ status は draft に戻る。
    assert second["status"] == "draft"
    assert second["approved_at"] is None


async def test_update_note_status_marks_published(migrated_db: Path) -> None:
    row = await note_db.upsert_note(
        note_date="2026-09-17",
        title="t",
        body_markdown="b",
        source_pick_ids=[],
        model_version="anthropic:test",
        has_price_mention_warning=False,
    )

    updated = await note_db.update_note_status(
        str(row["note_id"]),
        status="published",
        published_at="2026-09-17T10:00:00+09:00",
        published_url="https://note.com/example/n/xxx",
    )

    assert updated is not None
    assert updated["status"] == "published"
    assert updated["published_url"] == "https://note.com/example/n/xxx"


async def test_update_note_status_returns_none_for_missing_id(migrated_db: Path) -> None:
    result = await note_db.update_note_status("does-not-exist", status="approved")

    assert result is None


async def test_list_recent_notes_orders_newest_first(migrated_db: Path) -> None:
    for d in ("2026-09-15", "2026-09-17", "2026-09-16"):
        await note_db.upsert_note(
            note_date=d,
            title="t",
            body_markdown="b",
            source_pick_ids=[],
            model_version="anthropic:test",
            has_price_mention_warning=False,
        )

    rows = await note_db.list_recent_notes(limit=10)

    assert [r["note_date"] for r in rows] == ["2026-09-17", "2026-09-16", "2026-09-15"]
