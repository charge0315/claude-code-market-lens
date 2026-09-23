"""過去日リプレイの学習集計（🆕 P37）の検証."""

from __future__ import annotations

from pathlib import Path

import pytest

from backend.services.db import replay_db
from backend.services.ledger.outcome_resolver import HorizonOutcome
from backend.services.replay import learning
from backend.services.replay.selection import ReplayPick


def _row(composite: float, excess: float, *, trend: float = 50.0, ml: float | None = None) -> dict[str, object]:
    contributions: dict[str, object] = {"technical": {"score": composite}}
    if ml is not None:
        contributions["ml_prediction"] = {"score": ml}
    return {
        "composite_score": composite,
        "trend_score": trend,
        "source_contributions": contributions,
        "realized_return": excess + 0.001,
        "excess_return": excess,
        "win": excess + 0.001 > 0,
        "hit_target": excess > 0.05,
        "hit_stop": excess < -0.05,
    }


def test_performance_stats() -> None:
    rows = [_row(60.0, 0.02), _row(55.0, -0.04), _row(70.0, 0.06), _row(50.0, 0.0)]

    stats = learning.performance_stats(rows)

    assert stats["n"] == 4
    assert stats["win_rate"] == pytest.approx(0.75)
    assert stats["avg_excess"] == pytest.approx(0.01)
    assert stats["hit_target_rate"] == pytest.approx(0.25)


def test_performance_stats_empty() -> None:
    assert learning.performance_stats([]) == {"n": 0}


def test_composite_calibration_table_buckets_by_five_points() -> None:
    rows = [_row(61.0, 0.01), _row(63.0, -0.02), _row(66.0, 0.01), _row(71.0, 0.02)]

    table = learning.composite_calibration_table(rows)

    assert table == [
        {"bucket_low": 60.0, "bucket_high": 65.0, "n": 2, "win_rate": 0.5},
        {"bucket_low": 65.0, "bucket_high": 70.0, "n": 1, "win_rate": 1.0},
        {"bucket_low": 70.0, "bucket_high": 75.0, "n": 1, "win_rate": 1.0},
    ]


def test_factor_ics_reports_rank_correlation_per_factor() -> None:
    rows = [_row(50.0 + i, i / 100.0, trend=100.0 - i, ml=float(i)) for i in range(25)]

    ics = learning.factor_ics(rows)

    assert ics["composite"] == pytest.approx(1.0)
    assert ics["technical"] == pytest.approx(1.0)
    assert ics["ml_prediction"] == pytest.approx(1.0)
    assert ics["trend"] == pytest.approx(-1.0)
    assert ics["fundamental"] is None  # リプレイでは入力なし


async def test_compute_summary_end_to_end(migrated_db: Path) -> None:
    await replay_db.create_run("run-1", start_date="2021-10-01", end_date="2022-10-01", config={})
    picks = [
        ReplayPick(
            horizon_type="short_term",
            symbol=f"{1000 + i}",
            issued_at="2021-12-01",
            rank=i + 1,
            entry=100.0,
            stop=95.0,
            target=110.0,
            close=100.0,
            composite_score=50.0 + i,
            concordance=1.0,
            direction="bullish",
            recommendation="HOLD",
            trend_score=50.0,
            ml_prediction_rate=None,
            score_breakdown={},
            source_contributions={"technical": {"score": 50.0 + i}},
        )
        for i in range(25)
    ]
    await replay_db.insert_picks("run-1", picks, model_version=None)
    pending = await replay_db.list_pending_picks("run-1")
    for p in pending:
        i = int(str(p["symbol"])) - 1000
        outs = [
            HorizonOutcome(h, i / 100.0 - 0.1, i >= 10, False, False, "none", 0.0, 0.0, 0.0, i / 100.0)
            for h in (1, 2, 3)
        ]
        await replay_db.record_outcomes("run-1", str(p["pick_id"]), outs, resolved_on="2021-12-08", status="filled")

    summary = await learning.compute_summary("run-1")

    assert _dig(summary, "horizons", "short_term", "3", "performance", "n") == 25
    assert _dig(summary, "horizons", "short_term", "3", "factor_ics", "technical") == pytest.approx(1.0)
    # リプレイで入力の無いファクター（ファンダメンタル・センチメント）は既定重みで埋めず、重み計算から外す
    assert _dig(summary, "ic_weights", "short_term") == {"technical": 1.0}
    assert _dig(summary, "calibration", "short_term", "method") in {"platt", "isotonic"}
    assert _dig(summary, "horizons", "mid_term", "20", "performance") == {"n": 0}


def _dig(obj: object, *keys: str) -> object:
    """入れ子 dict をキー列でたどる（サマリは JSON 保存用に dict[str, object] で型付けしているため）."""
    for key in keys:
        assert isinstance(obj, dict), key
        obj = obj[key]
    return obj
