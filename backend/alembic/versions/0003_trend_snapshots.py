"""trend_snapshots テーブル — Trend Tracking Agent のスナップショット

`plans/01_PRD` §5.5「最新トレンド（Trend Tracking Agent）」。1 行 = ある時点で
収集・分析した構造化トレンド一覧のスナップショット。TTL（既定 3 時間）内は再利用する。

Revision ID: 0003_trend_snapshots
Revises: 0002_api_costs
Create Date: 2026-09-11
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003_trend_snapshots"
down_revision: str | None = "0002_api_costs"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "trend_snapshots",
        sa.Column("snapshot_at", sa.String(32), primary_key=True),  # ISO8601 JST
        sa.Column("status", sa.String(16), nullable=False),  # ok / mock / not_configured / llm_error / no_signals
        sa.Column("model", sa.String(64), nullable=False),
        sa.Column("trends", sa.Text(), nullable=False),  # JSON: list[Trend]
        sa.Column("signal_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("source_summary", sa.String(256), nullable=False, server_default=""),
        sa.Column("created_at", sa.String(32), nullable=False),
    )
    op.create_index("ix_trend_snapshots_created", "trend_snapshots", ["created_at"])


def downgrade() -> None:
    op.drop_table("trend_snapshots")
