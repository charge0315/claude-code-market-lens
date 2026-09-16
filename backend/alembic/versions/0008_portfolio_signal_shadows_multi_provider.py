"""portfolio_signal_shadows の一意制約を (signal_id, challenger_version) 複合へ変更（🆕 マルチLLM併用）

これまで `signal_id` 単独の UNIQUE インデックスだったため、1判定につき shadow は高々1件
（Gemini 固定）しか記録できなかった。LLM プロバイダを機能ごとに選択・併用できるようにする
変更に伴い、同一 signal_id に対して複数プロバイダ（例: Gemini + OpenAI）の shadow 判定を
併記できるよう、一意制約を (signal_id, challenger_version) の複合キーへ変更する。

Revision ID: 0008_portfolio_signal_shadows_multi_provider
Revises: 0007_portfolio_signal_shadows
Create Date: 2026-09-16
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0008_portfolio_signal_shadows_multi_provider"
down_revision: str | None = "0007_portfolio_signal_shadows"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_index("ix_portfolio_signal_shadows_signal_id", table_name="portfolio_signal_shadows")
    op.create_index(
        "ix_portfolio_signal_shadows_signal_id_challenger",
        "portfolio_signal_shadows",
        ["signal_id", "challenger_version"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("ix_portfolio_signal_shadows_signal_id_challenger", table_name="portfolio_signal_shadows")
    op.create_index("ix_portfolio_signal_shadows_signal_id", "portfolio_signal_shadows", ["signal_id"], unique=True)
