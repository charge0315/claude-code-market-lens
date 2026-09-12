"""training_batch_runs テーブル — 銘柄別モデル日次学習バッチの試行監査ログ（P9）

Market Lens `training_batch_runs` から移植（変更なし）。Celery beat による日次学習バッチ
（`services/learning/per_ticker_training_service.py`）が、当日そのモデルタイプで
試行済み（成功/失敗いずれも）の銘柄を記録する INSERT-only の監査ログ。1日あたりの学習件数
上限判定と、同一銘柄への当日中の再挑戦を避けるために使う。

Revision ID: 0004_training_batch_runs
Revises: 0003_trend_snapshots
Create Date: 2026-09-12
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004_training_batch_runs"
down_revision: str | None = "0003_trend_snapshots"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "training_batch_runs",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("run_date", sa.String(10), nullable=False),  # YYYY-MM-DD（JST）
        sa.Column("ticker", sa.String(16), nullable=False),
        sa.Column("model_type", sa.String(32), nullable=False),  # xgboost / random_forest / lstm / transformer
        sa.Column("status", sa.String(16), nullable=False),  # completed / failed
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.String(32), nullable=False),
    )
    op.create_index("ix_training_batch_runs_date_type", "training_batch_runs", ["run_date", "model_type"])


def downgrade() -> None:
    op.drop_table("training_batch_runs")
