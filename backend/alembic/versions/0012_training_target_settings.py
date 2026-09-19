"""training_target_settings / training_target_tickers テーブル追加（🆕 学習対象設定）

継続学習パイプラインは従来「東証全銘柄固定」でユニバースを回しており、ユーザーが学習対象を
絞り込む手段が無かった。学習対象モード（ポートフォリオ／ピック銘柄／全銘柄／カスタムリスト）
と並列学習プロセス数の上限を、`.env`（再起動必須）ではなく DB で即時反映できるよう永続化する。

`training_target_settings` は常に `id="default"` の単一行（`model_champions` と同様の
Upsert パターン）。行が無い場合はアプリ層で `target_mode="all"`, `max_parallel_workers=4`
にフォールバックし、既存の全銘柄学習動作と完全後方互換にする。

`training_target_tickers` はカスタムリストの銘柄コード集合。`added_at` は差分学習の優先度
判定（学習対象への追加が最終学習より後なら未学習扱いにする）に使う。

Revision ID: 0012_training_target_settings
Revises: 0011_pick_pool_snapshots
Create Date: 2026-09-20
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0012_training_target_settings"
down_revision: str | None = "0011_pick_pool_snapshots"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "training_target_settings",
        sa.Column("id", sa.String(16), primary_key=True),
        sa.Column("target_mode", sa.String(16), nullable=False, server_default="all"),
        sa.Column("max_parallel_workers", sa.Integer(), nullable=False, server_default="4"),
        sa.Column("updated_at", sa.String(32), nullable=False),
    )
    op.create_table(
        "training_target_tickers",
        sa.Column("ticker", sa.String(8), primary_key=True),
        sa.Column("added_at", sa.String(32), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("training_target_tickers")
    op.drop_table("training_target_settings")
