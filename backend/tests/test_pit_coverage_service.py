"""PIT特徴量スナップショットの収集進捗集計の検証（🆕 P29）."""

from __future__ import annotations

from pathlib import Path

import pytest

from backend import config
from backend.services.db import pit_snapshot_db
from backend.services.learning import pit_feature_service as pit_fs
from backend.services.registry import pit_coverage_service


async def test_all_groups_zero_when_no_snapshots(migrated_db: Path) -> None:
    status = await pit_coverage_service.build_pit_coverage_status()

    assert status.features_enabled is False  # 既定 OFF
    assert len(status.groups) == 3
    for g in status.groups:
        assert g.collected_days == 0
        assert g.ready is False
        assert g.remaining_days == g.min_coverage_days


async def test_fundamental_group_counts_distinct_days(migrated_db: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        pit_coverage_service, "settings", config.settings.model_copy(update={"pit_min_coverage_days": 2})
    )
    for d in ("2026-09-16", "2026-09-17"):
        await pit_snapshot_db.upsert_fundamental_snapshot(
            snapshot_date=d,
            code="7203",
            source="vault_frontmatter",
            data_as_of=None,
            per_forecast=None,
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
            created_at=f"{d}T16:45:00+09:00",
        )

    status = await pit_coverage_service.build_pit_coverage_status()

    fund = next(g for g in status.groups if g.group == pit_fs.FUNDAMENTAL_GROUP)
    assert fund.collected_days == 2
    assert fund.remaining_days == 0
    assert fund.ready is True


async def test_sentiment_groups_are_independent(migrated_db: Path) -> None:
    await pit_snapshot_db.upsert_sentiment_snapshot(
        snapshot_date="2026-09-17",
        code="7203",
        source="keyword",
        news_count=3,
        keyword_score=0.6,
        created_at="2026-09-17T16:50:00+09:00",
    )

    status = await pit_coverage_service.build_pit_coverage_status()

    keyword = next(g for g in status.groups if g.group == pit_fs.sentiment_group("keyword"))
    llm = next(g for g in status.groups if g.group == pit_fs.sentiment_group("llm"))
    assert keyword.collected_days == 1
    assert llm.collected_days == 0


async def test_features_enabled_reflects_settings(migrated_db: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        pit_coverage_service, "settings", config.settings.model_copy(update={"pit_features_enabled": True})
    )
    status = await pit_coverage_service.build_pit_coverage_status()
    assert status.features_enabled is True
