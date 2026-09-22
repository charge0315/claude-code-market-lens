"""pit_supply_demand_snapshots テーブル追加（🆕 需給軸、中長期ピック限定）

週末信用取引残高（J-Quants `/markets/margin-interest`）を、`pit_fundamental_snapshots` /
`pit_sentiment_snapshots` と同じ point-in-time（時点整合）append-only パターンで記録する。
`services/scoring/supply_demand_analyzer.py` が算出した信用倍率（買い残÷売り残）を
`orchestrator.py` の llm_overlay ステージから fire-and-forget で書き込む。中長期ピック限定
（ユーザー指示）のため、短期ピック実行では行が増えない。

Revision ID: 0013_pit_supply_demand_snapshots
Revises: 0012_training_target_settings
Create Date: 2026-09-22
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0013_pit_supply_demand_snapshots"
down_revision: str | None = "0012_training_target_settings"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "pit_supply_demand_snapshots",
        sa.Column("snapshot_id", sa.String(36), primary_key=True),
        sa.Column("snapshot_date", sa.String(10), nullable=False),
        sa.Column("code", sa.String(8), nullable=False),
        sa.Column("data_as_of", sa.String(10), nullable=True),
        sa.Column("long_volume", sa.Float(), nullable=True),
        sa.Column("short_volume", sa.Float(), nullable=True),
        sa.Column("margin_ratio", sa.Float(), nullable=True),
        sa.Column("margin_ratio_prev", sa.Float(), nullable=True),
        sa.Column("created_at", sa.String(32), nullable=False),
        sa.UniqueConstraint("snapshot_date", "code", name="uq_pit_supply_demand_date_code"),
    )
    op.create_index("ix_pit_supply_demand_code_date", "pit_supply_demand_snapshots", ["code", "snapshot_date"])


def downgrade() -> None:
    op.drop_index("ix_pit_supply_demand_code_date", table_name="pit_supply_demand_snapshots")
    op.drop_table("pit_supply_demand_snapshots")
