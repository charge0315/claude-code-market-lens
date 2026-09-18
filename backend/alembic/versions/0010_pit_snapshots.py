"""pit_fundamental_snapshots / pit_sentiment_snapshots テーブル追加（🆕 P29）

Vault 由来ファンダメンタル・ニュースセンチメントを ML 学習特徴量として使うための
point-in-time（時点整合）台帳。`plans/03_システム設計.md` §1.8 に対応。

Vault `Tickers/*.md` は日次スクレイピングで上書き更新される「現在値」ファイルであり過去
バージョンを持たないため、実装日から前向きに日次スナップショットを積み上げる以外に
時点整合な特徴量を得る経路が無い（過去分は原理的に復元不能）。本テーブルは append-only
（過去日の行を書き換える経路をコード上に持たない）。

Revision ID: 0010_pit_snapshots
Revises: 0009_daily_notes
Create Date: 2026-09-18
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0010_pit_snapshots"
down_revision: str | None = "0009_daily_notes"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "pit_fundamental_snapshots",
        sa.Column("snapshot_id", sa.String(36), primary_key=True),
        sa.Column("snapshot_date", sa.String(10), nullable=False),
        sa.Column("code", sa.String(8), nullable=False),
        sa.Column("source", sa.String(32), nullable=False),
        sa.Column("data_as_of", sa.String(10), nullable=True),
        sa.Column("per_forecast", sa.Float(), nullable=True),
        sa.Column("pbr", sa.Float(), nullable=True),
        sa.Column("roe", sa.Float(), nullable=True),
        sa.Column("equity_ratio", sa.Float(), nullable=True),
        sa.Column("dividend_yield_forecast", sa.Float(), nullable=True),
        sa.Column("eps_forecast", sa.Float(), nullable=True),
        sa.Column("bps", sa.Float(), nullable=True),
        sa.Column("market_cap_oku", sa.Float(), nullable=True),
        sa.Column("shares_outstanding", sa.Integer(), nullable=True),
        sa.Column("last_earnings_date", sa.String(10), nullable=True),
        sa.Column("last_earnings_type", sa.String(16), nullable=True),
        sa.Column("sector33", sa.String(64), nullable=True),
        sa.Column("sector17", sa.String(64), nullable=True),
        sa.Column("scale_cat", sa.String(16), nullable=True),
        sa.Column("market", sa.String(32), nullable=True),
        sa.Column("extra", sa.Text(), nullable=True),
        sa.Column("created_at", sa.String(32), nullable=False),
        sa.UniqueConstraint("snapshot_date", "code", name="uq_pit_fund_date_code"),
    )
    op.create_index("ix_pit_fund_code_date", "pit_fundamental_snapshots", ["code", "snapshot_date"])

    op.create_table(
        "pit_sentiment_snapshots",
        sa.Column("snapshot_id", sa.String(36), primary_key=True),
        sa.Column("snapshot_date", sa.String(10), nullable=False),
        sa.Column("code", sa.String(8), nullable=False),
        sa.Column("source", sa.String(16), nullable=False),  # "keyword" / "llm"
        sa.Column("news_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("keyword_positive", sa.Float(), nullable=True),
        sa.Column("keyword_negative", sa.Float(), nullable=True),
        sa.Column("keyword_score", sa.Float(), nullable=True),
        sa.Column("llm_sentiment_label", sa.String(20), nullable=True),
        sa.Column("llm_sentiment_score", sa.Float(), nullable=True),
        sa.Column("llm_impact_score", sa.Float(), nullable=True),
        sa.Column("llm_confidence", sa.Float(), nullable=True),
        sa.Column("created_at", sa.String(32), nullable=False),
        sa.UniqueConstraint("snapshot_date", "code", "source", name="uq_pit_sent_date_code_source"),
    )
    op.create_index("ix_pit_sent_code_date", "pit_sentiment_snapshots", ["code", "snapshot_date"])


def downgrade() -> None:
    op.drop_index("ix_pit_sent_code_date", table_name="pit_sentiment_snapshots")
    op.drop_table("pit_sentiment_snapshots")
    op.drop_index("ix_pit_fund_code_date", table_name="pit_fundamental_snapshots")
    op.drop_table("pit_fundamental_snapshots")
