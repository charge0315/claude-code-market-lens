"""pit_earnings_surprise_snapshots テーブル追加（🆕 決算サプライズ・予想修正モメンタム軸）

決算実績・会社予想（J-Quants `/fins/summary`）から算出した決算サプライズ（本決算実績 vs
直前開示の通期予想）・予想修正モメンタム（今回開示 vs 前回開示の通期予想）を、
`pit_fundamental_snapshots` / `pit_supply_demand_snapshots` と同じ point-in-time（時点整合）
append-only パターンで記録する。`services/scoring/earnings_surprise_analyzer.py` が算出した
値を `orchestrator.py` の llm_overlay ステージから fire-and-forget で書き込む。需給軸と異なり
短期・中長期の両方のピック実行で行が増える。

Revision ID: 0014_pit_earnings_surprise_snapshots
Revises: 0013_pit_supply_demand_snapshots
Create Date: 2026-09-22
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0014_pit_earnings_surprise_snapshots"
down_revision: str | None = "0013_pit_supply_demand_snapshots"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "pit_earnings_surprise_snapshots",
        sa.Column("snapshot_id", sa.String(36), primary_key=True),
        sa.Column("snapshot_date", sa.String(10), nullable=False),
        sa.Column("code", sa.String(8), nullable=False),
        sa.Column("data_as_of", sa.String(10), nullable=True),
        sa.Column("fiscal_year_end", sa.String(10), nullable=True),
        sa.Column("period_type", sa.String(8), nullable=True),
        sa.Column("surprise_op_rate", sa.Float(), nullable=True),
        sa.Column("revision_op_rate", sa.Float(), nullable=True),
        sa.Column("revision_classification", sa.String(16), nullable=True),
        sa.Column("created_at", sa.String(32), nullable=False),
        sa.UniqueConstraint("snapshot_date", "code", name="uq_pit_earnings_surprise_date_code"),
    )
    op.create_index("ix_pit_earnings_surprise_code_date", "pit_earnings_surprise_snapshots", ["code", "snapshot_date"])


def downgrade() -> None:
    op.drop_index("ix_pit_earnings_surprise_code_date", table_name="pit_earnings_surprise_snapshots")
    op.drop_table("pit_earnings_surprise_snapshots")
