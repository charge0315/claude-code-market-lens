"""`model_stats_db`（🆕 P15、学習状態可視化の集計クエリ）の検証."""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path

from backend.services.db import model_registry_db, model_stats_db


async def _register_and_promote(
    *, version: str, model_type: str, ticker: str, val_metrics: Mapping[str, object]
) -> None:
    await model_registry_db.upsert_model(
        version=version, model_type=model_type, ticker=ticker, objective="regression", val_metrics=val_metrics
    )
    await model_registry_db.set_champion(f"{model_type}:{ticker}", version, promoted_by="quality_gate")


async def test_count_trained_tickers_by_model_type_excludes_pool(migrated_db: Path) -> None:
    await model_registry_db.upsert_model(version="v1", model_type="xgboost", ticker="7203")
    await model_registry_db.upsert_model(version="v2", model_type="xgboost", ticker="6758")
    await model_registry_db.upsert_model(version="v3", model_type="xgboost", ticker="7203")  # 同一銘柄の再学習
    await model_registry_db.upsert_model(version="v4", model_type="ml_pool", ticker="__pool__")

    counts = await model_stats_db.count_trained_tickers_by_model_type()

    assert counts["xgboost"] == 2  # DISTINCT ticker（7203 の再学習は1件のまま）
    assert "ml_pool" not in counts  # __pool__ は除外


async def test_list_per_ticker_champion_metrics_excludes_non_per_ticker_lanes(migrated_db: Path) -> None:
    metrics = {"rmse": 0.1, "skill": 0.2}
    await _register_and_promote(version="v1", model_type="xgboost", ticker="7203", val_metrics=metrics)
    # 銘柄別ではないレーン（mid_term 等）は対象外。
    await model_registry_db.upsert_model(version="pool-v1", model_type="mid_term")
    await model_registry_db.set_champion("mid_term", "pool-v1", promoted_by="manual")

    rows = await model_stats_db.list_per_ticker_champion_metrics()

    lanes = [r["lane"] for r in rows]
    assert lanes == ["xgboost:7203"]
    assert json.loads(str(rows[0]["val_metrics"])) == {"rmse": 0.1, "skill": 0.2}


async def test_get_last_trained_at_by_model_type_takes_max_excludes_pool(migrated_db: Path) -> None:
    await model_registry_db.upsert_model(
        version="v1", model_type="xgboost", ticker="7203", objective="regression", trained_at="2026-09-01T00:00:00"
    )
    await model_registry_db.upsert_model(
        version="v2", model_type="xgboost", ticker="6758", objective="regression", trained_at="2026-09-10T00:00:00"
    )
    await model_registry_db.upsert_model(
        version="v3", model_type="ml_pool", ticker="__pool__", objective="regression", trained_at="2026-09-12T00:00:00"
    )

    latest = await model_stats_db.get_last_trained_at_by_model_type()

    assert latest["xgboost"] == "2026-09-10T00:00:00"
    assert "ml_pool" not in latest


async def test_get_training_counts_by_date_groups_by_date_type_status(migrated_db: Path) -> None:
    from backend.services.db.training_batch_db import insert_training_batch_run

    await insert_training_batch_run(run_date="2026-09-10", ticker="7203", model_type="xgboost", status="completed")
    await insert_training_batch_run(run_date="2026-09-10", ticker="6758", model_type="xgboost", status="completed")
    await insert_training_batch_run(run_date="2026-09-10", ticker="9432", model_type="xgboost", status="failed")
    await insert_training_batch_run(run_date="2026-09-11", ticker="7203", model_type="lstm", status="completed")

    rows = await model_stats_db.get_training_counts_by_date(since="2026-09-01")

    by_key = {(r["run_date"], r["model_type"], r["status"]): r["n"] for r in rows}
    assert by_key[("2026-09-10", "xgboost", "completed")] == 2
    assert by_key[("2026-09-10", "xgboost", "failed")] == 1
    assert by_key[("2026-09-11", "lstm", "completed")] == 1


async def test_get_training_counts_by_date_respects_since_filter(migrated_db: Path) -> None:
    from backend.services.db.training_batch_db import insert_training_batch_run

    await insert_training_batch_run(run_date="2026-08-01", ticker="7203", model_type="xgboost", status="completed")
    await insert_training_batch_run(run_date="2026-09-10", ticker="6758", model_type="xgboost", status="completed")

    rows = await model_stats_db.get_training_counts_by_date(since="2026-09-01")

    assert [r["run_date"] for r in rows] == ["2026-09-10"]
