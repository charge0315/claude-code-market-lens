"""baseline schema — Alpha Forge

予測台帳・決着記録・評価指標・モデルレジストリ・昇格ゲート・ドリフト・
推論トレース・ポートフォリオ・通知の各テーブルを新規作成する
（`plans/03_システム設計.md` §1）。Market Lens の per-ticker マスタ等は
データ層フェーズ（P2）で必要な分だけ足す。

Revision ID: 0001_baseline
Revises:
Create Date: 2026-09-11
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0001_baseline"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # --- CL-1 予測台帳 ---
    op.create_table(
        "prediction_ledger",
        sa.Column("pick_id", sa.String(36), primary_key=True),
        sa.Column("run_id", sa.String(36), nullable=False),
        sa.Column("issued_at", sa.String(32), nullable=False),  # ISO8601 JST
        sa.Column("horizon_type", sa.String(16), nullable=False),  # mid_term / short_term
        sa.Column("symbol", sa.String(8), nullable=False),  # 4 桁コード
        sa.Column("direction", sa.String(8), nullable=False),  # bullish / bearish / neutral
        sa.Column("entry", sa.Float(), nullable=False),
        sa.Column("stop", sa.Float(), nullable=False),
        sa.Column("target", sa.Float(), nullable=False),
        sa.Column("sub_score_technical", sa.Float(), nullable=False),
        sa.Column("sub_score_trend", sa.Float(), nullable=False),
        sa.Column("sub_score_fundamental", sa.Float(), nullable=False),
        sa.Column("sub_score_sentiment", sa.Float(), nullable=False),
        sa.Column("composite_score", sa.Float(), nullable=False),
        sa.Column("concordance", sa.Float(), nullable=False),  # 0–1
        sa.Column("confidence_raw", sa.Float(), nullable=False),  # 較正前 0–100
        sa.Column("confidence", sa.Float(), nullable=False),  # 事後較正後 0–100
        sa.Column("confidence_bucket", sa.String(8), nullable=False),  # high / mid / low
        sa.Column("feature_snapshot", sa.Text(), nullable=False),  # JSON: 全特徴量
        sa.Column("rationale_struct", sa.Text(), nullable=False),  # JSON
        sa.Column("rationale_text", sa.Text(), nullable=False),
        sa.Column("model_version", sa.String(64), nullable=False),
        sa.Column("source_contributions", sa.Text(), nullable=False),  # JSON
        sa.Column("is_shadow", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.String(32), nullable=False),
    )
    op.create_index("ix_ledger_horizon_issued", "prediction_ledger", ["horizon_type", "issued_at"])
    op.create_index("ix_ledger_symbol_issued", "prediction_ledger", ["symbol", "issued_at"])
    op.create_index("ix_ledger_model_version", "prediction_ledger", ["model_version"])
    op.create_index("ix_ledger_is_shadow", "prediction_ledger", ["is_shadow"])

    # --- CL-2 決着記録（1 ピックにつき複数ホライズン） ---
    op.create_table(
        "pick_outcomes",
        sa.Column("outcome_id", sa.String(36), primary_key=True),
        sa.Column("pick_id", sa.String(36), sa.ForeignKey("prediction_ledger.pick_id"), nullable=False),
        sa.Column("horizon_days", sa.Integer(), nullable=False),  # 短期 1/2/3、中長期 5/20/60
        sa.Column("resolved_at", sa.String(32), nullable=False),
        sa.Column("realized_return", sa.Float(), nullable=False),
        sa.Column("win", sa.Integer(), nullable=False),
        sa.Column("hit_stop", sa.Integer(), nullable=False),
        sa.Column("hit_target", sa.Integer(), nullable=False),
        sa.Column("first_hit", sa.String(8), nullable=False),  # stop / target / none
        sa.Column("mfe", sa.Float(), nullable=False),
        sa.Column("mae", sa.Float(), nullable=False),
        sa.Column("benchmark_return", sa.Float(), nullable=False),  # TOPIX 同期間
        sa.Column("excess_return", sa.Float(), nullable=False),
        sa.Column("confidence_bucket", sa.String(8), nullable=False),
        sa.Column("direction", sa.String(8), nullable=False),
        sa.UniqueConstraint("pick_id", "horizon_days", name="uq_outcome_pick_horizon"),
    )
    op.create_index("ix_outcome_resolved_at", "pick_outcomes", ["resolved_at"])
    op.create_index("ix_outcome_bucket_dir", "pick_outcomes", ["confidence_bucket", "direction"])

    # --- CL-3 評価指標（時系列） ---
    op.create_table(
        "eval_snapshots",
        sa.Column("snapshot_id", sa.String(36), primary_key=True),
        sa.Column("computed_at", sa.String(32), nullable=False),
        sa.Column("scope", sa.String(16), nullable=False),  # mid_term / short_term / combined
        sa.Column("model_version", sa.String(64), nullable=True),
        sa.Column("metric_name", sa.String(32), nullable=False),
        sa.Column("metric_value", sa.Float(), nullable=False),
        sa.Column("sample_n", sa.Integer(), nullable=False),
        sa.Column("horizon_days", sa.Integer(), nullable=True),
        sa.Column("confidence_bucket", sa.String(8), nullable=True),
    )
    op.create_index("ix_eval_scope_metric_time", "eval_snapshots", ["scope", "metric_name", "computed_at"])

    op.create_table(
        "calibration_curves",
        sa.Column("curve_id", sa.String(36), primary_key=True),
        sa.Column("computed_at", sa.String(32), nullable=False),
        sa.Column("scope", sa.String(16), nullable=False),
        sa.Column("horizon_days", sa.Integer(), nullable=True),
        sa.Column("direction", sa.String(8), nullable=True),
        sa.Column("points", sa.Text(), nullable=False),  # JSON: [{p_pred, p_obs, n}]
        sa.Column("brier", sa.Float(), nullable=True),
        sa.Column("is_calibrated", sa.Integer(), nullable=False, server_default="0"),
    )

    op.create_table(
        "source_ablations",
        sa.Column("ablation_id", sa.String(36), primary_key=True),
        sa.Column("computed_at", sa.String(32), nullable=False),
        sa.Column("quarter", sa.String(8), nullable=False),  # 2026Q3
        sa.Column("excluded_source", sa.String(32), nullable=False),
        sa.Column("metric_name", sa.String(32), nullable=False),
        sa.Column("metric_delta", sa.Float(), nullable=False),  # 除外時 − 全部入り
        sa.Column("sample_n", sa.Integer(), nullable=False),
    )

    # --- CL-6 / N1 モデルレジストリ & 昇格 ---
    op.create_table(
        "model_registry",
        sa.Column("version", sa.String(64), primary_key=True),
        sa.Column("model_type", sa.String(32), nullable=False),  # xgboost / random_forest / lstm / transformer / *_pool
        sa.Column("ticker", sa.String(16), nullable=False, server_default="__pool__"),
        sa.Column("objective", sa.String(16), nullable=False, server_default="classification"),
        sa.Column("trained_at", sa.String(32), nullable=False),
        sa.Column("artifact_path", sa.String(512), nullable=False),
        sa.Column("val_metrics", sa.Text(), nullable=False),  # JSON
        sa.Column("feature_list", sa.Text(), nullable=False),  # JSON
    )
    op.create_index("ix_registry_type_ticker", "model_registry", ["model_type", "ticker"])

    op.create_table(
        "model_champions",
        sa.Column("lane", sa.String(32), primary_key=True),  # mid_term_pool / short_term_pool / per_ticker_xgb ...
        sa.Column("champion_version", sa.String(64), sa.ForeignKey("model_registry.version"), nullable=False),
        sa.Column("promoted_at", sa.String(32), nullable=False),
        sa.Column("promoted_by", sa.String(16), nullable=False, server_default="manual"),
    )

    op.create_table(
        "model_promotions",
        sa.Column("promotion_id", sa.String(36), primary_key=True),
        sa.Column("lane", sa.String(32), nullable=False),
        sa.Column("challenger_version", sa.String(64), nullable=False),
        sa.Column("champion_version", sa.String(64), nullable=True),
        sa.Column("evaluated_at", sa.String(32), nullable=False),
        sa.Column("holdout_delta", sa.Float(), nullable=False),  # challenger − champion
        sa.Column("calib_regressed", sa.Integer(), nullable=False),
        sa.Column("paper_perf_delta", sa.Float(), nullable=False),
        sa.Column("paper_days", sa.Integer(), nullable=False),
        sa.Column("verdict", sa.String(16), nullable=False),  # propose_promote / hold / reject
        sa.Column("applied", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("rationale", sa.Text(), nullable=False),  # JSON
    )
    op.create_index("ix_promotion_lane_time", "model_promotions", ["lane", "evaluated_at"])

    op.create_table(
        "shadow_predictions",
        sa.Column("shadow_id", sa.String(36), primary_key=True),
        sa.Column("pick_id", sa.String(36), sa.ForeignKey("prediction_ledger.pick_id"), nullable=True),
        sa.Column("run_id", sa.String(36), nullable=False),
        sa.Column("challenger_version", sa.String(64), nullable=False),
        sa.Column("symbol", sa.String(8), nullable=False),
        sa.Column("horizon_type", sa.String(16), nullable=False),
        sa.Column("issued_at", sa.String(32), nullable=False),
        sa.Column("direction", sa.String(8), nullable=False),
        sa.Column("entry", sa.Float(), nullable=False),
        sa.Column("stop", sa.Float(), nullable=False),
        sa.Column("target", sa.Float(), nullable=False),
        sa.Column("confidence_raw", sa.Float(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("payload", sa.Text(), nullable=False),  # JSON
    )
    op.create_index("ix_shadow_challenger_time", "shadow_predictions", ["challenger_version", "issued_at"])

    # --- CL-4 / N5 ドリフト検知 ---
    op.create_table(
        "drift_snapshots",
        sa.Column("drift_id", sa.String(36), primary_key=True),
        sa.Column("computed_at", sa.String(32), nullable=False),
        sa.Column("feature_name", sa.String(64), nullable=False),
        sa.Column("psi", sa.Float(), nullable=False),
        sa.Column("baseline_window", sa.String(64), nullable=False),
        sa.Column("current_window", sa.String(64), nullable=False),
        sa.Column("drift_flag", sa.Integer(), nullable=False),
        sa.Column("triggered_retrain", sa.Integer(), nullable=False, server_default="0"),
    )
    op.create_index("ix_drift_time_feature", "drift_snapshots", ["computed_at", "feature_name"])

    # --- VZ-6 / N4 AI 思考トレース（リプレイ可能） ---
    op.create_table(
        "inference_traces",
        sa.Column("trace_id", sa.String(36), primary_key=True),
        sa.Column("run_id", sa.String(36), nullable=False),
        sa.Column("pick_id", sa.String(36), nullable=True),  # 確定後に紐付け
        sa.Column("symbol", sa.String(8), nullable=False),
        sa.Column("horizon_type", sa.String(16), nullable=False),
        sa.Column("started_at", sa.String(32), nullable=False),
        sa.Column("finished_at", sa.String(32), nullable=True),
        sa.Column("status", sa.String(16), nullable=False),  # running / done / failed
        sa.Column("stage", sa.String(16), nullable=False),  # collect/subscore/llm_overlay/synthesis/bracket/verify
        sa.Column("stage_status", sa.String(16), nullable=False),  # pending/running/done/failed
        sa.Column("stage_seq", sa.Integer(), nullable=False),
        sa.Column("payload", sa.Text(), nullable=False),  # JSON: 中間結果
        sa.Column("event_at", sa.String(32), nullable=False),  # SSE 再生用
    )
    op.create_index("ix_trace_run_seq", "inference_traces", ["run_id", "stage_seq"])
    op.create_index("ix_trace_symbol_started", "inference_traces", ["symbol", "started_at"])

    # --- PF ポートフォリオ & 通知 ---
    op.create_table(
        "portfolios",
        sa.Column("holding_id", sa.String(36), primary_key=True),
        sa.Column("symbol", sa.String(8), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("avg_cost", sa.Float(), nullable=False),
        sa.Column("acquired_at", sa.String(32), nullable=False),
        sa.Column("created_at", sa.String(32), nullable=False),
        sa.Column("updated_at", sa.String(32), nullable=False),
        sa.UniqueConstraint("symbol", "acquired_at", name="uq_holding_symbol_acquired"),
    )

    op.create_table(
        "portfolio_signals",
        sa.Column("signal_id", sa.String(36), primary_key=True),
        sa.Column("symbol", sa.String(8), nullable=False),
        sa.Column("evaluated_at", sa.String(32), nullable=False),
        sa.Column("action", sa.String(16), nullable=False),  # hold / trim / stop_loss / add
        sa.Column("entry", sa.Float(), nullable=True),  # 買い増し時のみ
        sa.Column("stop", sa.Float(), nullable=False),
        sa.Column("target", sa.Float(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("rationale", sa.Text(), nullable=False),
        sa.Column(
            "status", sa.String(16), nullable=False, server_default="proposed"
        ),  # proposed/approved/rejected/executed
        sa.Column("fill_report", sa.Text(), nullable=True),  # JSON: 人間が戻す約定結果
    )
    op.create_index("ix_signal_status_time", "portfolio_signals", ["status", "evaluated_at"])

    op.create_table(
        "push_subscriptions",
        sa.Column("endpoint", sa.String(512), primary_key=True),
        sa.Column("p256dh", sa.String(256), nullable=False),
        sa.Column("auth", sa.String(128), nullable=False),
        sa.Column("created_at", sa.String(32), nullable=False),
        sa.Column("user_agent", sa.String(256), nullable=True),
        sa.Column("revoked", sa.Integer(), nullable=False, server_default="0"),
    )

    op.create_table(
        "notifications",
        sa.Column("notification_id", sa.String(36), primary_key=True),
        sa.Column("run_date", sa.String(16), nullable=False),
        sa.Column("ticker", sa.String(8), nullable=False),
        sa.Column("kind", sa.String(32), nullable=False),  # entry / stop / target / add / trim ...
        sa.Column("channel", sa.String(16), nullable=False, server_default="in_app"),  # in_app / web_push
        sa.Column("body", sa.Text(), nullable=False),  # JSON: 銘柄・アクション・根拠・3値・確度
        sa.Column("created_at", sa.String(32), nullable=False),
        sa.Column("read_at", sa.String(32), nullable=True),
        sa.UniqueConstraint("run_date", "ticker", "kind", name="uq_notification_dedupe"),
    )

    op.create_table(
        "eod_reviews",
        sa.Column("review_date", sa.String(16), primary_key=True),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("learned_heuristics", sa.Text(), nullable=False),  # JSON
        sa.Column("created_at", sa.String(32), nullable=False),
    )


def downgrade() -> None:
    for table in (
        "eod_reviews",
        "notifications",
        "push_subscriptions",
        "portfolio_signals",
        "portfolios",
        "inference_traces",
        "drift_snapshots",
        "shadow_predictions",
        "model_promotions",
        "model_champions",
        "model_registry",
        "source_ablations",
        "calibration_curves",
        "eval_snapshots",
        "pick_outcomes",
        "prediction_ledger",
    ):
        op.drop_table(table)
