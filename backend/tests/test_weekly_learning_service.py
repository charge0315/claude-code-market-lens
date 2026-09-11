"""weekly_learning_service（週次学習差分サマリ、🆕）のテスト."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import cast

import pytest

from backend.services.db import drift_db, eval_db, model_registry_db
from backend.services.jst_time import JST
from backend.services.ledger import weekly_learning_service as svc

_NOW = datetime(2026, 9, 11, 12, 0, 0, tzinfo=JST)
_OLD = "2026-08-01T12:00:00+09:00"  # window_days=7 のカットオフ（9/4頃）より前
_RECENT = "2026-09-10T12:00:00+09:00"  # カットオフより後


async def test_metric_delta_compares_before_and_after_cutoff(migrated_db: Path) -> None:
    await eval_db.insert_eval_snapshot(
        scope="mid_term", metric_name="win_rate", metric_value=0.50, sample_n=10, computed_at=_OLD
    )
    await eval_db.insert_eval_snapshot(
        scope="mid_term", metric_name="win_rate", metric_value=0.60, sample_n=15, computed_at=_RECENT
    )

    summary = await svc.build_weekly_learning_summary(window_days=7, now=_NOW)

    delta_list = cast("list[dict[str, object]]", summary["metric_deltas"])
    deltas = {(d["scope"], d["metric"]): d for d in delta_list}
    delta = deltas[("mid_term", "win_rate")]
    assert delta["before"] == pytest.approx(0.50)
    assert delta["after"] == pytest.approx(0.60)
    assert delta["delta"] == pytest.approx(0.10)


async def test_metric_with_no_history_is_omitted(migrated_db: Path) -> None:
    summary = await svc.build_weekly_learning_summary(window_days=7, now=_NOW)
    assert summary["metric_deltas"] == []


async def test_recent_promotions_are_included_and_old_ones_excluded(migrated_db: Path) -> None:
    await model_registry_db.insert_promotion(
        promotion_id="p-old",
        lane="mid_term",
        challenger_version="v1",
        champion_version="v0",
        holdout_delta=0.1,
        calib_regressed=False,
        paper_perf_delta=0.1,
        paper_days=25,
        verdict="propose_promote",
        rationale={},
        evaluated_at=_OLD,
    )
    await model_registry_db.insert_promotion(
        promotion_id="p-recent",
        lane="mid_term",
        challenger_version="v2",
        champion_version="v1",
        holdout_delta=0.2,
        calib_regressed=False,
        paper_perf_delta=0.2,
        paper_days=25,
        verdict="propose_promote",
        rationale={},
        evaluated_at=_RECENT,
    )

    summary = await svc.build_weekly_learning_summary(window_days=7, now=_NOW)

    promotions = cast("list[dict[str, object]]", summary["recent_promotions"])
    ids = {p["promotion_id"] for p in promotions}
    assert "p-recent" in ids
    assert "p-old" not in ids


async def test_recent_drift_flags_are_included_and_non_flagged_excluded(migrated_db: Path) -> None:
    await drift_db.insert_drift_snapshot(
        feature_name="score_breakdown.technical",
        psi=0.4,
        baseline_window="x",
        current_window="y",
        drift_flag=True,
        computed_at=_RECENT,
    )
    await drift_db.insert_drift_snapshot(
        feature_name="atr_14",
        psi=0.05,
        baseline_window="x",
        current_window="y",
        drift_flag=False,
        computed_at=_RECENT,
    )
    await drift_db.insert_drift_snapshot(
        feature_name="trend_score",
        psi=0.5,
        baseline_window="x",
        current_window="y",
        drift_flag=True,
        computed_at=_OLD,
    )

    summary = await svc.build_weekly_learning_summary(window_days=7, now=_NOW)

    drift_flags = cast("list[dict[str, object]]", summary["recent_drift_flags"])
    flagged = {d["feature_name"] for d in drift_flags}
    assert flagged == {"score_breakdown.technical"}


async def test_summary_shape(migrated_db: Path) -> None:
    summary = await svc.build_weekly_learning_summary(window_days=14, now=_NOW)
    assert summary["window_days"] == 14
    assert "as_of" in summary
    assert isinstance(summary["metric_deltas"], list)
    assert isinstance(summary["recent_promotions"], list)
    assert isinstance(summary["recent_drift_flags"], list)
