"""Alembic マイグレーションの検証（baseline の適用と巻き戻し）."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from alembic import command
from alembic.config import Config

_REPO_ROOT = Path(__file__).resolve().parents[2]

_EXPECTED_TABLES = {
    "prediction_ledger",
    "pick_outcomes",
    "eval_snapshots",
    "calibration_curves",
    "source_ablations",
    "model_registry",
    "model_champions",
    "model_promotions",
    "shadow_predictions",
    "drift_snapshots",
    "inference_traces",
    "portfolios",
    "portfolio_signals",
    "push_subscriptions",
    "notifications",
    "eod_reviews",
    "api_costs",
    "trend_snapshots",
    "training_batch_runs",
}


def _alembic_config(db_path: Path) -> Config:
    cfg = Config(str(_REPO_ROOT / "backend" / "alembic.ini"))
    cfg.set_main_option("script_location", str(_REPO_ROOT / "backend" / "alembic"))
    cfg.set_main_option("sqlalchemy.url", f"sqlite:///{db_path.as_posix()}")
    return cfg


def _table_names(db_path: Path) -> set[str]:
    with sqlite3.connect(db_path) as conn:
        rows = conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    return {r[0] for r in rows}


def test_baseline_upgrade_creates_all_tables(tmp_path: Path) -> None:
    db_path = tmp_path / "m.db"
    command.upgrade(_alembic_config(db_path), "head")
    assert _EXPECTED_TABLES.issubset(_table_names(db_path))


def test_baseline_downgrade_removes_domain_tables(tmp_path: Path) -> None:
    db_path = tmp_path / "m.db"
    cfg = _alembic_config(db_path)
    command.upgrade(cfg, "head")
    command.downgrade(cfg, "base")
    assert _EXPECTED_TABLES.isdisjoint(_table_names(db_path))
