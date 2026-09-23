"""リプレイ専用台帳（🆕 P37）の読み書き検証."""

from __future__ import annotations

from pathlib import Path

from backend.services.db import replay_db
from backend.services.ledger.outcome_resolver import HorizonOutcome
from backend.services.replay.selection import ReplayPick


def _pick(symbol: str, issued_at: str = "2021-12-01", horizon_type: str = "short_term") -> ReplayPick:
    return ReplayPick(
        horizon_type=horizon_type,
        symbol=symbol,
        issued_at=issued_at,
        rank=1,
        entry=100.0,
        stop=95.0,
        target=110.0,
        close=100.0,
        composite_score=65.0,
        concordance=1.0,
        direction="bullish",
        recommendation="BUY",
        trend_score=55.0,
        ml_prediction_rate=0.4,
        score_breakdown={"technical": 65.0},
        source_contributions={"technical": {"score": 65.0}},
    )


def _outcome(h: int, realized: float) -> HorizonOutcome:
    return HorizonOutcome(h, realized, realized > 0, False, False, "none", 0.02, -0.01, 0.001, realized - 0.001)


async def test_run_lifecycle(migrated_db: Path) -> None:
    await replay_db.create_run("run-1", start_date="2021-10-01", end_date="2026-09-18", config={"k": 1})

    await replay_db.update_run("run-1", status="running", cursor_date="2021-12-01", pid=123)
    run = await replay_db.get_run("run-1")

    assert run is not None
    assert run["status"] == "running"
    assert run["cursor_date"] == "2021-12-01"
    assert run["config"] == {"k": 1}
    assert [r["run_id"] for r in await replay_db.list_runs()] == ["run-1"]
    assert await replay_db.get_run("missing") is None


async def test_insert_picks_is_idempotent_for_same_day(migrated_db: Path) -> None:
    """途中で落ちた日をやり直しても、同じ (horizon, 日付, 銘柄) は二重登録されない."""
    await replay_db.create_run("run-1", start_date="2021-10-01", end_date="2026-09-18", config={})

    await replay_db.insert_picks("run-1", [_pick("7203"), _pick("6758")], model_version="replay-pool@2021-11-30")
    await replay_db.insert_picks("run-1", [_pick("7203")], model_version="replay-pool@2021-11-30")

    pending = await replay_db.list_pending_picks("run-1")
    assert sorted(str(p["symbol"]) for p in pending) == ["6758", "7203"]
    assert pending[0]["model_version"] == "replay-pool@2021-11-30"


async def test_record_outcomes_upserts_and_marks_resolution(migrated_db: Path) -> None:
    await replay_db.create_run("run-1", start_date="2021-10-01", end_date="2026-09-18", config={})
    await replay_db.insert_picks("run-1", [_pick("7203")], model_version=None)
    pick_id = str((await replay_db.list_pending_picks("run-1"))[0]["pick_id"])

    await replay_db.record_outcomes("run-1", pick_id, [_outcome(1, 0.01)], resolved_on="2021-12-03", status="pending")
    await replay_db.record_outcomes(
        "run-1",
        pick_id,
        [_outcome(1, 0.02), _outcome(2, -0.01), _outcome(3, 0.03)],
        resolved_on="2021-12-07",
        status="filled",
    )

    assert await replay_db.list_pending_picks("run-1") == []
    rows = await replay_db.list_resolved("run-1", horizon_days=1)
    assert len(rows) == 1
    assert rows[0]["realized_return"] == 0.02  # 上書き（最新の解決結果）
    assert rows[0]["source_contributions"] == {"technical": {"score": 65.0}}
    assert rows[0]["composite_score"] == 65.0


async def test_retrains_and_counts(migrated_db: Path) -> None:
    await replay_db.create_run("run-1", start_date="2021-10-01", end_date="2026-09-18", config={})
    await replay_db.insert_retrain("run-1", trained_on="2021-11-30", model_version="v1", metrics={"auc": 0.55})
    await replay_db.insert_picks("run-1", [_pick("7203"), _pick("6758", horizon_type="mid_term")], model_version=None)

    retrains = await replay_db.list_retrains("run-1")
    assert retrains == [{"trained_on": "2021-11-30", "model_version": "v1", "metrics": {"auc": 0.55}}]
    assert await replay_db.count_picks("run-1") == {"short_term": 1, "mid_term": 1}
