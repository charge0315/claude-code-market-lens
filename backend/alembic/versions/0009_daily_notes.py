"""daily_notes テーブル追加（🆕 日次noteドラフト自動生成・承認制配信）

本日のAIピック分析結果（entry/stop/target を除く）をもとに有料note記事の下書きを自動生成し、
人間が確認・編集・承認してから note.com へ手動投稿するための状態追跡テーブル。
`note_date` が一意（1 日 1 件）。

Revision ID: 0009_daily_notes
Revises: 0008_portfolio_signal_shadows_multi_provider
Create Date: 2026-09-17
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0009_daily_notes"
down_revision: str | None = "0008_portfolio_signal_shadows_multi_provider"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "daily_notes",
        sa.Column("note_id", sa.String(36), primary_key=True),
        sa.Column("note_date", sa.String(10), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("body_markdown", sa.Text(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="draft"),
        sa.Column("source_pick_ids", sa.Text(), nullable=False),
        sa.Column("model_version", sa.String(64), nullable=False),
        sa.Column("has_price_mention_warning", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("generated_at", sa.String(32), nullable=False),
        sa.Column("approved_at", sa.String(32), nullable=True),
        sa.Column("published_at", sa.String(32), nullable=True),
        sa.Column("published_url", sa.Text(), nullable=True),
    )
    op.create_index("ix_daily_notes_note_date", "daily_notes", ["note_date"], unique=True)


def downgrade() -> None:
    op.drop_index("ix_daily_notes_note_date", table_name="daily_notes")
    op.drop_table("daily_notes")
