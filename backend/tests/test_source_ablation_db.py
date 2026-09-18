"""`source_ablations` の読み書き検証（🆕 P29）."""

from __future__ import annotations

from pathlib import Path

from backend.services.db import source_ablation_db


async def test_insert_and_list_ablations(migrated_db: Path) -> None:
    await source_ablation_db.insert_ablation(
        computed_at="2026-09-18T04:00:00+09:00",
        quarter="2026Q3",
        excluded_source="pit_fundamental",
        metric_name="auc",
        metric_delta=-0.03,
        sample_n=120,
    )
    await source_ablation_db.insert_ablation(
        computed_at="2026-09-18T04:00:00+09:00",
        quarter="2026Q3",
        excluded_source="pit_sentiment_keyword",
        metric_name="auc",
        metric_delta=-0.01,
        sample_n=120,
    )

    rows = await source_ablation_db.list_ablations()
    assert len(rows) == 2
    assert {r["excluded_source"] for r in rows} == {"pit_fundamental", "pit_sentiment_keyword"}


async def test_list_ablations_filters_by_quarter_and_source(migrated_db: Path) -> None:
    await source_ablation_db.insert_ablation(
        computed_at="2026-09-18T04:00:00+09:00",
        quarter="2026Q3",
        excluded_source="pit_fundamental",
        metric_name="auc",
        metric_delta=-0.03,
        sample_n=120,
    )
    await source_ablation_db.insert_ablation(
        computed_at="2026-12-18T04:00:00+09:00",
        quarter="2026Q4",
        excluded_source="pit_fundamental",
        metric_name="auc",
        metric_delta=-0.02,
        sample_n=140,
    )

    q3_rows = await source_ablation_db.list_ablations(quarter="2026Q3")
    assert len(q3_rows) == 1
    assert q3_rows[0]["metric_delta"] == -0.03

    filtered = await source_ablation_db.list_ablations(excluded_source="pit_fundamental")
    assert len(filtered) == 2


async def test_list_ablations_empty_when_none_recorded(migrated_db: Path) -> None:
    assert await source_ablation_db.list_ablations() == []
