"""training_batch_runs に data_source 列を追加（🆕 P17、学習データソース内訳の可視化）

学習に成功した銘柄が yfinance / J-Quants のどちらのデータで学習されたかを記録する。
モデルラボの「カバレッジ（データソース別）」表示（東証全銘柄のうちどれだけを
yfinance だけで学習でき、どれだけ J-Quants フォールバックが必要だったか）に使う。
既存行は NULL のままとし、新規挿入分のみ埋まる（フェイルソフト・後方互換）。

Revision ID: 0005_training_batch_data_source
Revises: 0004_training_batch_runs
Create Date: 2026-09-12
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005_training_batch_data_source"
down_revision: str | None = "0004_training_batch_runs"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("training_batch_runs", sa.Column("data_source", sa.String(16), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("training_batch_runs") as batch_op:
        batch_op.drop_column("data_source")
