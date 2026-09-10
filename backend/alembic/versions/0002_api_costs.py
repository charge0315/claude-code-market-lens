"""api_costs テーブル — LLM 呼び出しのトークン・費用の台帳

`plans/01_PRD` §6「API コスト計測（LLM 呼び出しのトークン・費用を台帳化）」。
`(log_date, feature, model)` を主キーにし、同日・同機能・同モデルの呼び出しは
1 行に集約（call_count とトークン量を加算）する。

Revision ID: 0002_api_costs
Revises: 0001_baseline
Create Date: 2026-09-11
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002_api_costs"
down_revision: str | None = "0001_baseline"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "api_costs",
        sa.Column("log_date", sa.String(16), nullable=False),  # YYYY-MM-DD (JST)
        sa.Column("feature", sa.String(48), nullable=False),  # stock_pick / trend_analyzer / chat ...
        sa.Column("model", sa.String(64), nullable=False),
        sa.Column("call_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("input_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("output_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("cache_read_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("cache_write_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("est_cost_usd", sa.Float(), nullable=False, server_default="0"),
        sa.Column("pricing_known", sa.Integer(), nullable=False, server_default="1"),
        sa.PrimaryKeyConstraint("log_date", "feature", "model", name="pk_api_costs"),
    )
    op.create_index("ix_api_costs_log_date", "api_costs", ["log_date"])


def downgrade() -> None:
    op.drop_table("api_costs")
