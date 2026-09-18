"""`pit_fundamental_snapshots` / `pit_sentiment_snapshots` の読み書き検証（🆕 P29）."""

from __future__ import annotations

from pathlib import Path

from backend.services.db import pit_snapshot_db


async def _upsert_fund(*, snapshot_date: str, code: str, per_forecast: float | None = None) -> None:
    await pit_snapshot_db.upsert_fundamental_snapshot(
        snapshot_date=snapshot_date,
        code=code,
        source="vault_frontmatter",
        data_as_of=None,
        per_forecast=per_forecast,
        pbr=None,
        roe=None,
        equity_ratio=None,
        dividend_yield_forecast=None,
        eps_forecast=None,
        bps=None,
        market_cap_oku=None,
        shares_outstanding=None,
        last_earnings_date=None,
        last_earnings_type=None,
        sector33=None,
        sector17=None,
        scale_cat=None,
        market=None,
        extra=None,
        created_at="2026-09-18T16:45:00+09:00",
    )


async def test_upsert_and_list_fundamental_range(migrated_db: Path) -> None:
    await _upsert_fund(snapshot_date="2026-09-18", code="7203", per_forecast=15.2)
    await _upsert_fund(snapshot_date="2026-09-17", code="7203", per_forecast=14.9)
    await _upsert_fund(snapshot_date="2026-09-18", code="9984", per_forecast=30.0)

    rows = await pit_snapshot_db.list_fundamental_range(codes=["7203"], since="2026-09-01", until="2026-09-30")
    assert [r["snapshot_date"] for r in rows] == ["2026-09-17", "2026-09-18"]
    assert rows[-1]["per_forecast"] == 15.2


async def test_upsert_fundamental_same_day_overwrites_not_appends(migrated_db: Path) -> None:
    """同一 `(snapshot_date, code)` は upsert で上書き（append-only は「過去日を書き換えない」
    意味であり、同日中の再実行は許容する設計）."""
    await _upsert_fund(snapshot_date="2026-09-18", code="7203", per_forecast=15.2)
    await _upsert_fund(snapshot_date="2026-09-18", code="7203", per_forecast=16.0)

    rows = await pit_snapshot_db.list_fundamental_range(codes=["7203"], since="2026-09-01", until="2026-09-30")
    assert len(rows) == 1
    assert rows[0]["per_forecast"] == 16.0


async def test_list_fundamental_range_all_codes_when_none(migrated_db: Path) -> None:
    await _upsert_fund(snapshot_date="2026-09-18", code="7203")
    await _upsert_fund(snapshot_date="2026-09-18", code="9984")

    rows = await pit_snapshot_db.list_fundamental_range(codes=None, since="2026-09-01", until="2026-09-30")
    assert {r["code"] for r in rows} == {"7203", "9984"}


async def test_upsert_and_list_sentiment_range_by_source(migrated_db: Path) -> None:
    await pit_snapshot_db.upsert_sentiment_snapshot(
        snapshot_date="2026-09-18",
        code="7203",
        source="keyword",
        news_count=5,
        keyword_positive=3.0,
        keyword_negative=1.0,
        keyword_score=0.62,
        created_at="2026-09-18T16:50:00+09:00",
    )
    await pit_snapshot_db.upsert_sentiment_snapshot(
        snapshot_date="2026-09-18",
        code="7203",
        source="llm",
        news_count=5,
        llm_sentiment_label="positive",
        llm_sentiment_score=0.5,
        llm_impact_score=40.0,
        llm_confidence=60.0,
        created_at="2026-09-18T08:50:00+09:00",
    )

    keyword_rows = await pit_snapshot_db.list_sentiment_range(
        codes=["7203"], since="2026-09-01", until="2026-09-30", source="keyword"
    )
    llm_rows = await pit_snapshot_db.list_sentiment_range(
        codes=["7203"], since="2026-09-01", until="2026-09-30", source="llm"
    )
    assert len(keyword_rows) == 1 and keyword_rows[0]["keyword_score"] == 0.62
    assert len(llm_rows) == 1 and llm_rows[0]["llm_sentiment_label"] == "positive"
    # source ごとに独立した行として共存し、互いの列を上書きしない。
    assert keyword_rows[0]["llm_sentiment_label"] is None
    assert llm_rows[0]["keyword_score"] is None


async def test_distinct_fundamental_snapshot_dates(migrated_db: Path) -> None:
    await _upsert_fund(snapshot_date="2026-09-16", code="7203")
    await _upsert_fund(snapshot_date="2026-09-17", code="9984")
    await _upsert_fund(snapshot_date="2026-09-17", code="7203")

    dates = await pit_snapshot_db.distinct_fundamental_snapshot_dates(since="2026-09-01", until="2026-09-30")
    assert dates == ["2026-09-16", "2026-09-17"]
