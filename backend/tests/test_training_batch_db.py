"""training_batch_db（銘柄別モデル日次学習バッチの監査ログ、P9）のテスト."""

from __future__ import annotations

from pathlib import Path

from backend.services.db import model_registry_db, training_batch_db


async def test_insert_and_get_attempted_tickers(migrated_db: Path) -> None:
    await training_batch_db.insert_training_batch_run(
        run_date="2026-09-12", ticker="7203", model_type="xgboost", status="completed"
    )
    await training_batch_db.insert_training_batch_run(
        run_date="2026-09-12", ticker="9984", model_type="xgboost", status="failed", error="boom"
    )

    attempted = await training_batch_db.get_attempted_tickers("2026-09-12", "xgboost")
    assert attempted == {"7203", "9984"}


async def test_get_attempted_tickers_is_scoped_by_model_type(migrated_db: Path) -> None:
    await training_batch_db.insert_training_batch_run(
        run_date="2026-09-12", ticker="7203", model_type="xgboost", status="completed"
    )
    await training_batch_db.insert_training_batch_run(
        run_date="2026-09-12", ticker="9984", model_type="lstm", status="completed"
    )

    assert await training_batch_db.get_attempted_tickers("2026-09-12", "xgboost") == {"7203"}
    assert await training_batch_db.get_attempted_tickers("2026-09-12", "lstm") == {"9984"}


async def test_get_attempted_tickers_is_scoped_by_run_date(migrated_db: Path) -> None:
    await training_batch_db.insert_training_batch_run(
        run_date="2026-09-11", ticker="7203", model_type="xgboost", status="completed"
    )

    assert await training_batch_db.get_attempted_tickers("2026-09-12", "xgboost") == set()


async def test_get_latest_data_source_by_model_type_counts_latest_attempt_only(migrated_db: Path) -> None:
    """同一銘柄が複数回学習されている場合、最新（id最大）の試行のデータソースのみ数える（🆕 P17）."""
    await training_batch_db.insert_training_batch_run(
        run_date="2026-09-01", ticker="7203", model_type="xgboost", status="completed", data_source="yfinance"
    )
    # 同じ銘柄の再学習で J-Quants にフォールバックした（最新の方を採用すべき）。
    await training_batch_db.insert_training_batch_run(
        run_date="2026-09-10", ticker="7203", model_type="xgboost", status="completed", data_source="jquants"
    )
    await training_batch_db.insert_training_batch_run(
        run_date="2026-09-10", ticker="6758", model_type="xgboost", status="completed", data_source="yfinance"
    )
    # 失敗行・data_source 無し・別モデルタイプは対象外。
    await training_batch_db.insert_training_batch_run(
        run_date="2026-09-10", ticker="9432", model_type="xgboost", status="failed", data_source=None
    )
    await training_batch_db.insert_training_batch_run(
        run_date="2026-09-10", ticker="1111", model_type="lstm", status="completed", data_source="jquants"
    )

    breakdown = await training_batch_db.get_latest_data_source_by_model_type()

    assert breakdown["xgboost"] == {"jquants": 1, "yfinance": 1}
    assert breakdown["lstm"] == {"jquants": 1}


async def test_get_latest_trained_at_by_ticker_takes_max_per_ticker(migrated_db: Path) -> None:
    await model_registry_db.upsert_model(
        version="v1", model_type="xgboost", ticker="7203", objective="regression", trained_at="2026-09-01T00:00:00"
    )
    await model_registry_db.upsert_model(
        version="v2", model_type="xgboost", ticker="7203", objective="regression", trained_at="2026-09-05T00:00:00"
    )
    await model_registry_db.upsert_model(
        version="v3", model_type="xgboost", ticker="9984", objective="regression", trained_at="2026-09-03T00:00:00"
    )
    # 別モデルタイプは対象外
    await model_registry_db.upsert_model(
        version="v4",
        model_type="random_forest",
        ticker="6758",
        objective="regression",
        trained_at="2026-09-09T00:00:00",
    )

    latest = await training_batch_db.get_latest_trained_at_by_ticker("xgboost")

    assert latest == {"7203": "2026-09-05T00:00:00", "9984": "2026-09-03T00:00:00"}
