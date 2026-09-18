"""pick_pool_snapshots テーブル追加（🆕 P30）

`services/picks/pipeline.py::run_picks` が算出する候補プール全銘柄の 4 分析+ML スコア・
合成スコアは、従来は実行中のローカル変数（`scored`）にしか存在せず永続化されていなかった。
日次パイプラインログ（Vault ノート、`plans/04_タスクリスト.md` P30）が「候補プールで選出した
銘柄一覧」「絞り込まれた銘柄一覧」「4分析+MLの結果」「銘柄ごとの合成スコア」を後から再構成
できるよう、1 バッチ実行（`batch_run_id` = `prediction_ledger.run_id` と同じ値）につき
候補プール全銘柄を append-only で記録する。

Revision ID: 0011_pick_pool_snapshots
Revises: 0010_pit_snapshots
Create Date: 2026-09-18
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0011_pick_pool_snapshots"
down_revision: str | None = "0010_pit_snapshots"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "pick_pool_snapshots",
        sa.Column("snapshot_id", sa.String(36), primary_key=True),
        sa.Column("batch_run_id", sa.String(36), nullable=False),
        sa.Column("horizon_type", sa.String(16), nullable=False),
        sa.Column("issued_at", sa.String(32), nullable=False),
        sa.Column("symbol", sa.String(8), nullable=False),
        sa.Column("composite_score", sa.Float(), nullable=True),
        sa.Column("direction", sa.String(16), nullable=True),
        sa.Column("concordance", sa.Float(), nullable=True),
        sa.Column("score_breakdown", sa.Text(), nullable=True),  # JSON: technical/ml_prediction/fundamental/sentiment
        sa.Column("trend_score", sa.Float(), nullable=True),  # 4分析の trend（score_breakdown 外・別経路で算出）
        sa.Column("ml_prediction_rate", sa.Float(), nullable=True),
        sa.Column("is_shortlisted", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.String(32), nullable=False),
    )
    op.create_index("ix_pick_pool_batch_run_id", "pick_pool_snapshots", ["batch_run_id"])
    op.create_index("ix_pick_pool_issued_at_horizon", "pick_pool_snapshots", ["issued_at", "horizon_type"])


def downgrade() -> None:
    op.drop_index("ix_pick_pool_issued_at_horizon", table_name="pick_pool_snapshots")
    op.drop_index("ix_pick_pool_batch_run_id", table_name="pick_pool_snapshots")
    op.drop_table("pick_pool_snapshots")
