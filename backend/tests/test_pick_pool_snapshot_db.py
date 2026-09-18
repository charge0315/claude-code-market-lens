"""`pick_pool_snapshot_db`（候補プール全銘柄の4分析+MLスコア）の検証（🆕 P30）."""

from __future__ import annotations

from pathlib import Path

from backend.services.db.pick_pool_snapshot_db import insert_pool_snapshots, list_pool_snapshots_for_date


def _row(symbol: str, *, is_shortlisted: bool, issued_at: str = "2026-09-18T07:30:00+09:00") -> dict[str, object]:
    return {
        "batch_run_id": "run-1",
        "horizon_type": "mid_term",
        "issued_at": issued_at,
        "symbol": symbol,
        "composite_score": 62.5,
        "direction": "bullish",
        "concordance": 0.75,
        "score_breakdown": {"technical": 60.0, "fundamental": 55.0, "sentiment": None},
        "trend_score": 58.0,
        "ml_prediction_rate": 0.61,
        "is_shortlisted": is_shortlisted,
    }


async def test_insert_and_list_roundtrip(migrated_db: Path) -> None:
    await insert_pool_snapshots([_row("7203", is_shortlisted=True), _row("6758", is_shortlisted=False)])

    rows = await list_pool_snapshots_for_date("2026-09-18", horizon_type="mid_term")

    assert {r["symbol"] for r in rows} == {"7203", "6758"}
    shortlisted = {r["symbol"]: r["is_shortlisted"] for r in rows}
    assert shortlisted == {"7203": True, "6758": False}
    row = next(r for r in rows if r["symbol"] == "7203")
    assert row["score_breakdown"] == {"technical": 60.0, "fundamental": 55.0, "sentiment": None}
    assert row["trend_score"] == 58.0
    assert row["composite_score"] == 62.5
    assert row["batch_run_id"] == "run-1"


async def test_list_orders_by_composite_score_desc_within_horizon(migrated_db: Path) -> None:
    low = _row("6758", is_shortlisted=False)
    low["composite_score"] = 40.0
    high = _row("7203", is_shortlisted=True)
    high["composite_score"] = 80.0
    await insert_pool_snapshots([low, high])

    rows = await list_pool_snapshots_for_date("2026-09-18", horizon_type="mid_term")
    assert [r["symbol"] for r in rows] == ["7203", "6758"]


async def test_list_filters_by_date_and_horizon(migrated_db: Path) -> None:
    await insert_pool_snapshots(
        [
            _row("7203", is_shortlisted=True, issued_at="2026-09-18T07:30:00+09:00"),
            _row("6758", is_shortlisted=True, issued_at="2026-09-17T07:30:00+09:00"),
        ]
    )
    other_horizon = _row("9984", is_shortlisted=True)
    other_horizon["horizon_type"] = "short_term"
    await insert_pool_snapshots([other_horizon])

    rows = await list_pool_snapshots_for_date("2026-09-18", horizon_type="mid_term")
    assert [r["symbol"] for r in rows] == ["7203"]


async def test_list_without_horizon_filter_returns_all_horizons_for_date(migrated_db: Path) -> None:
    other_horizon = _row("9984", is_shortlisted=True)
    other_horizon["horizon_type"] = "short_term"
    await insert_pool_snapshots([_row("7203", is_shortlisted=True), other_horizon])

    rows = await list_pool_snapshots_for_date("2026-09-18")
    assert {r["symbol"] for r in rows} == {"7203", "9984"}


async def test_insert_empty_rows_is_noop(migrated_db: Path) -> None:
    await insert_pool_snapshots([])
    assert await list_pool_snapshots_for_date("2026-09-18") == []
