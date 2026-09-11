"""PSI ドリフト検知の検証（CL-4 / N5）."""

from __future__ import annotations

import random
from pathlib import Path

from backend.models.pick import LedgerEntry, SubScores
from backend.services.db import drift_db
from backend.services.ledger import prediction_ledger as pl
from backend.services.registry import drift


def test_compute_psi_is_near_zero_for_identical_distributions() -> None:
    rng = random.Random(0)
    baseline = [rng.gauss(50, 10) for _ in range(200)]
    current = [rng.gauss(50, 10) for _ in range(200)]
    psi = drift.compute_psi(baseline, current)
    assert psi is not None and psi < 0.05


def test_compute_psi_is_large_for_shifted_distribution() -> None:
    rng = random.Random(0)
    baseline = [rng.gauss(50, 5) for _ in range(200)]
    current = [rng.gauss(80, 5) for _ in range(200)]  # 完全にシフトした分布
    psi = drift.compute_psi(baseline, current)
    assert psi is not None and psi > 0.5


def test_compute_psi_none_when_insufficient_samples() -> None:
    assert drift.compute_psi([1.0] * 5, [1.0] * 5) is None


def test_compute_psi_zero_when_baseline_constant() -> None:
    assert drift.compute_psi([50.0] * 30, [10.0] * 30) == 0.0


def _entry(pick_id: str, issued_at: str, technical: float) -> LedgerEntry:
    return LedgerEntry(
        pick_id=pick_id,
        run_id="r1",
        issued_at=issued_at,
        horizon_type="mid_term",
        symbol="7203",
        direction="bullish",
        entry=1000.0,
        stop=950.0,
        target=1100.0,
        sub_scores=SubScores(technical=technical, trend=55, fundamental=52, sentiment=50),
        composite_score=60.0,
        concordance=0.6,
        confidence_raw=70.0,
        confidence=70.0,
        confidence_bucket="high",
        feature_snapshot={"score_breakdown": {"technical": technical}, "atr_14": 20.0, "trend_score": 55.0},
        rationale_struct={},
        rationale_text="x",
        model_version="baseline-2026-09-11",
        source_contributions={},
        created_at=issued_at,
    )


async def test_list_feature_values_extracts_dotted_path(migrated_db: Path) -> None:
    await pl.insert_pick(_entry("p1", "2026-07-01T08:50:00+09:00", 62.0))
    await pl.insert_pick(_entry("p2", "2026-07-02T08:50:00+09:00", 70.0))
    values = await pl.list_feature_values(
        "score_breakdown.technical", since="2026-07-01T00:00:00", until="2026-07-03T00:00:00"
    )
    assert sorted(values) == [62.0, 70.0]


async def test_check_feature_drift_persists_snapshot(migrated_db: Path) -> None:
    rng = random.Random(3)
    for i in range(25):
        await pl.insert_pick(_entry(f"base{i}", f"2026-06-{(i % 27) + 1:02d}T08:50:00+09:00", rng.gauss(50, 5)))
    for i in range(25):
        await pl.insert_pick(_entry(f"cur{i}", f"2026-08-{(i % 27) + 1:02d}T08:50:00+09:00", rng.gauss(80, 5)))

    result = await drift.check_feature_drift(
        "score_breakdown.technical",
        baseline_start="2026-06-01T00:00:00",
        baseline_end="2026-07-01T00:00:00",
        current_start="2026-08-01T00:00:00",
        current_end="2026-09-01T00:00:00",
    )
    assert result is not None
    assert result.drift_flag is True  # 大きくシフトしているので閾値(0.2)超過

    stored = await drift_db.list_drift_snapshots(feature_name="score_breakdown.technical")
    assert len(stored) == 1
    assert stored[0]["drift_flag"] == 1


async def test_run_drift_batch_skips_features_with_insufficient_data(migrated_db: Path) -> None:
    await pl.insert_pick(_entry("only1", "2026-07-01T08:50:00+09:00", 60.0))
    results = await drift.run_drift_batch(
        baseline_start="2026-06-01T00:00:00",
        baseline_end="2026-07-15T00:00:00",
        current_start="2026-08-01T00:00:00",
        current_end="2026-09-01T00:00:00",
    )
    assert results == []  # サンプル不足で全特徴量スキップ
