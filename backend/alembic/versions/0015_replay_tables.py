"""過去日リプレイ学習の専用台帳（🆕 P37）

取得できる最古の日から 1 営業日ずつ「その日の大引け時点の情報だけ」でピックを再現し、以降の
実データで答え合わせした結果を記録する。本番の `prediction_ledger` / `pick_outcomes` とは
**完全に別テーブル**にする（ユーザー決定 2026-09-23）: 本番台帳に混ぜると、UI の「同確度
バケットの実測勝率」や昇格ゲートの「直近 20 営業日ペーパー成績」が実運用でない成績で汚れるため。

- `replay_runs`: 1 回のリプレイ実行（期間・進捗カーソル・状態・学習結果サマリ）。
  `cursor_date` は「処理を完了した最後のリプレイ日」で、再開時はその翌営業日から続ける。
- `replay_picks`: リプレイで確定したピック（3 値必須）。(run, horizon, 日付, 銘柄) で一意にし、
  途中で落ちた日をやり直しても重複しないようにする。
- `replay_outcomes`: ホライズン別の決着（`pick_outcomes` と同じ列構成）。
- `replay_retrains`: リプレイ内で断面プールモデルを学び直した履歴（評価指標）。

Revision ID: 0015_replay_tables
Revises: 0014_pit_earnings_surprise_snapshots
Create Date: 2026-09-23
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0015_replay_tables"
down_revision: str | None = "0014_pit_earnings_surprise_snapshots"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "replay_runs",
        sa.Column("run_id", sa.String(36), primary_key=True),
        sa.Column("status", sa.String(16), nullable=False),  # pending / running / completed / failed / stopped
        sa.Column("start_date", sa.String(10), nullable=False),
        sa.Column("end_date", sa.String(10), nullable=False),
        sa.Column("cursor_date", sa.String(10), nullable=True),
        sa.Column("config", sa.Text(), nullable=False),  # JSON
        sa.Column("summary", sa.Text(), nullable=True),  # JSON: 学習結果（IC 重み・較正・成績）
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("pid", sa.Integer(), nullable=True),
        sa.Column("heartbeat_at", sa.String(32), nullable=True),
        sa.Column("created_at", sa.String(32), nullable=False),
        sa.Column("updated_at", sa.String(32), nullable=False),
    )

    op.create_table(
        "replay_picks",
        sa.Column("pick_id", sa.String(36), primary_key=True),
        sa.Column("run_id", sa.String(36), sa.ForeignKey("replay_runs.run_id"), nullable=False),
        sa.Column("horizon_type", sa.String(16), nullable=False),
        sa.Column("issued_at", sa.String(10), nullable=False),
        sa.Column("symbol", sa.String(8), nullable=False),
        sa.Column("rank", sa.Integer(), nullable=False),
        sa.Column("entry", sa.Float(), nullable=False),
        sa.Column("stop", sa.Float(), nullable=False),
        sa.Column("target", sa.Float(), nullable=False),
        sa.Column("close", sa.Float(), nullable=False),
        sa.Column("composite_score", sa.Float(), nullable=False),
        sa.Column("concordance", sa.Float(), nullable=True),
        sa.Column("direction", sa.String(16), nullable=True),
        sa.Column("recommendation", sa.String(8), nullable=True),
        sa.Column("trend_score", sa.Float(), nullable=True),
        sa.Column("ml_prediction_rate", sa.Float(), nullable=True),
        sa.Column("score_breakdown", sa.Text(), nullable=False),  # JSON
        sa.Column("source_contributions", sa.Text(), nullable=False),  # JSON
        sa.Column("model_version", sa.String(64), nullable=True),  # ML ファクターに使ったリプレイ内モデル
        sa.Column("resolution_status", sa.String(16), nullable=False, server_default="pending"),
        sa.UniqueConstraint("run_id", "horizon_type", "issued_at", "symbol", name="uq_replay_pick_day"),
    )
    op.create_index("ix_replay_picks_run_status", "replay_picks", ["run_id", "resolution_status"])

    op.create_table(
        "replay_outcomes",
        sa.Column("pick_id", sa.String(36), sa.ForeignKey("replay_picks.pick_id"), primary_key=True),
        sa.Column("horizon_days", sa.Integer(), primary_key=True),
        sa.Column("run_id", sa.String(36), nullable=False),
        sa.Column("realized_return", sa.Float(), nullable=False),
        sa.Column("win", sa.Integer(), nullable=False),
        sa.Column("hit_stop", sa.Integer(), nullable=False),
        sa.Column("hit_target", sa.Integer(), nullable=False),
        sa.Column("first_hit", sa.String(8), nullable=False),
        sa.Column("mfe", sa.Float(), nullable=False),
        sa.Column("mae", sa.Float(), nullable=False),
        sa.Column("benchmark_return", sa.Float(), nullable=False),
        sa.Column("excess_return", sa.Float(), nullable=False),
        sa.Column("resolved_on", sa.String(10), nullable=False),
    )
    op.create_index("ix_replay_outcomes_run_horizon", "replay_outcomes", ["run_id", "horizon_days"])

    op.create_table(
        "replay_retrains",
        sa.Column("run_id", sa.String(36), sa.ForeignKey("replay_runs.run_id"), primary_key=True),
        sa.Column("trained_on", sa.String(10), primary_key=True),
        sa.Column("model_version", sa.String(64), nullable=False),
        sa.Column("metrics", sa.Text(), nullable=False),  # JSON
    )


def downgrade() -> None:
    op.drop_table("replay_retrains")
    op.drop_index("ix_replay_outcomes_run_horizon", table_name="replay_outcomes")
    op.drop_table("replay_outcomes")
    op.drop_index("ix_replay_picks_run_status", table_name="replay_picks")
    op.drop_table("replay_picks")
    op.drop_table("replay_runs")
