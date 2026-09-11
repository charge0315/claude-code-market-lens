"""`services/db/eod_review_db`（`eod_reviews` CRUD）の検証."""

from __future__ import annotations

from pathlib import Path

from backend.services.db.eod_review_db import get_eod_review, list_recent_eod_reviews, upsert_eod_review


async def test_get_eod_review_unknown_returns_none(migrated_db: Path) -> None:
    assert await get_eod_review("2026-06-02") is None


async def test_upsert_then_get_eod_review(migrated_db: Path) -> None:
    await upsert_eod_review(
        review_date="2026-06-02",
        summary="堅調な1日でした。",
        learned_heuristics=[{"heuristic": "h1", "evidence": "e1", "confidence": 0.5}],
    )

    row = await get_eod_review("2026-06-02")

    assert row is not None
    assert row["summary"] == "堅調な1日でした。"
    assert row["created_at"] is not None


async def test_upsert_overwrites_existing_review_date(migrated_db: Path) -> None:
    await upsert_eod_review(review_date="2026-06-02", summary="初回", learned_heuristics=[])
    await upsert_eod_review(review_date="2026-06-02", summary="再生成後", learned_heuristics=[])

    row = await get_eod_review("2026-06-02")

    assert row is not None
    assert row["summary"] == "再生成後"


async def test_list_recent_eod_reviews_returns_newest_first(migrated_db: Path) -> None:
    await upsert_eod_review(review_date="2026-06-01", summary="1日目", learned_heuristics=[])
    await upsert_eod_review(review_date="2026-06-03", summary="3日目", learned_heuristics=[])
    await upsert_eod_review(review_date="2026-06-02", summary="2日目", learned_heuristics=[])

    rows = await list_recent_eod_reviews(limit=2)

    assert [r["review_date"] for r in rows] == ["2026-06-03", "2026-06-02"]
