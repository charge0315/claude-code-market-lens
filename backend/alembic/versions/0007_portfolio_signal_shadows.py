"""portfolio_signal_shadows テーブル追加（🆕、AI 売買タイミング判定の Gemini 併記）

AI 売買タイミング判定（`portfolio_signals`）は Claude（公式パイプライン）の判定のみを
記録してきたが、AI ピック一覧と同様に Gemini（challenger）にも同一プロンプトで判定させ、
比較参考用に併記できるようにする。承認・却下・実約定判定には一切関与しない表示専用の
テーブル（`shadow_predictions` と同じ設計思想）。

Revision ID: 0007_portfolio_signal_shadows
Revises: 0006_portfolio_sell_history
Create Date: 2026-09-14
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0007_portfolio_signal_shadows"
down_revision: str | None = "0006_portfolio_sell_history"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "portfolio_signal_shadows",
        sa.Column("shadow_id", sa.String(36), primary_key=True),
        sa.Column("signal_id", sa.String(36), nullable=False),
        sa.Column("challenger_version", sa.String(64), nullable=False),
        sa.Column("action", sa.String(16), nullable=False),
        sa.Column("entry", sa.Float(), nullable=True),
        sa.Column("stop", sa.Float(), nullable=False),
        sa.Column("target", sa.Float(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("reasoning", sa.Text(), nullable=False),
        sa.Column("created_at", sa.String(32), nullable=False),
    )
    op.create_index("ix_portfolio_signal_shadows_signal_id", "portfolio_signal_shadows", ["signal_id"], unique=True)


def downgrade() -> None:
    op.drop_index("ix_portfolio_signal_shadows_signal_id", table_name="portfolio_signal_shadows")
    op.drop_table("portfolio_signal_shadows")
