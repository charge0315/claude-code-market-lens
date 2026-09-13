"""portfolio_sell_history テーブル追加（🆕 P26、保有銘柄の売却履歴）

これまで保有銘柄の削除（`DELETE /api/portfolio/holdings/{id}`）は行を単純に消すだけで、
実現損益や売却の記録が残らなかった。売却操作（`POST /api/portfolio/holdings/{id}/sell`）で
このテーブルへ1行追加してから、保有ロットを削除（全量売却）または株数を減算（一部売却）する。

Revision ID: 0006_portfolio_sell_history
Revises: 0005_training_batch_data_source
Create Date: 2026-09-13
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0006_portfolio_sell_history"
down_revision: str | None = "0005_training_batch_data_source"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "portfolio_sell_history",
        sa.Column("sell_id", sa.String(36), primary_key=True),
        # 全量売却なら元の holding_id をそのまま参照する意味は失われる（行が消えるため）ため
        # FK にはしない。参照用の識別子として保持するのみ。
        sa.Column("holding_id", sa.String(36), nullable=False),
        sa.Column("symbol", sa.String(8), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("avg_cost", sa.Float(), nullable=False),
        sa.Column("sell_price", sa.Float(), nullable=False),
        sa.Column("realized_pnl", sa.Float(), nullable=False),
        sa.Column("sold_at", sa.String(32), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("created_at", sa.String(32), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("portfolio_sell_history")
