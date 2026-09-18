"""`pick_pool_snapshots`（候補プール全銘柄の 4 分析+ML スコア・合成スコア）の読み書き（SQLAlchemy async）.

`plans/04_タスクリスト.md` P30。`services/picks/pipeline.py::run_picks` が 1 回のバッチ実行で
スコアリングした候補プール全銘柄（ショートリスト絞り込み前）を append-only で記録する。
日次パイプラインログ（`services/vault_report/pipeline_log_generator.py`）が「候補プール一覧」
「絞り込まれた銘柄一覧」「4分析+MLの結果」「合成スコア」を再構成するための唯一の永続化経路。
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Mapping, Sequence
from datetime import datetime

from sqlalchemy import text

from backend.services.db.database import get_db
from backend.services.jst_time import JST


async def insert_pool_snapshots(rows: Sequence[Mapping[str, object]]) -> None:
    """候補プール全銘柄ぶんのスナップショットを一括追加する（空なら何もしない）.

    各 row は {batch_run_id, horizon_type, issued_at, symbol, composite_score, direction,
    concordance, score_breakdown(dict|None), trend_score, ml_prediction_rate, is_shortlisted}
    を持つこと。`trend_score` は recommender の `score_breakdown`（technical/ml_prediction/
    fundamental/sentiment）とは別経路（`signal_scan_scoring.compute_trend_score`）で算出される
    4分析目（trend）のサブスコアのため、独立した列に持つ。
    """
    if not rows:
        return
    created_at = datetime.now(JST).isoformat(timespec="seconds")
    stmt = text("""
        INSERT INTO pick_pool_snapshots (
            snapshot_id, batch_run_id, horizon_type, issued_at, symbol,
            composite_score, direction, concordance, score_breakdown, trend_score,
            ml_prediction_rate, is_shortlisted, created_at
        ) VALUES (
            :snapshot_id, :batch_run_id, :horizon_type, :issued_at, :symbol,
            :composite_score, :direction, :concordance, :score_breakdown, :trend_score,
            :ml_prediction_rate, :is_shortlisted, :created_at
        )
        """)
    async with get_db() as db:
        for row in rows:
            await db.execute(
                stmt,
                {
                    "snapshot_id": str(uuid.uuid4()),
                    "batch_run_id": row["batch_run_id"],
                    "horizon_type": row["horizon_type"],
                    "issued_at": row["issued_at"],
                    "symbol": row["symbol"],
                    "composite_score": row.get("composite_score"),
                    "direction": row.get("direction"),
                    "concordance": row.get("concordance"),
                    "score_breakdown": json.dumps(row.get("score_breakdown") or {}, ensure_ascii=False),
                    "trend_score": row.get("trend_score"),
                    "ml_prediction_rate": row.get("ml_prediction_rate"),
                    "is_shortlisted": 1 if row.get("is_shortlisted") else 0,
                    "created_at": created_at,
                },
            )


def _parse_row(row: dict[str, object]) -> dict[str, object]:
    row["score_breakdown"] = json.loads(str(row.get("score_breakdown") or "{}"))
    row["is_shortlisted"] = bool(row.get("is_shortlisted"))
    return row


async def list_pool_snapshots_for_date(date: str, *, horizon_type: str | None = None) -> list[dict[str, object]]:
    """指定日（`issued_at` の日付部分）の候補プールスナップショットを合成スコア降順で返す."""
    clause = "AND horizon_type = :horizon_type" if horizon_type else ""
    params: dict[str, object] = {"date": date}
    if horizon_type:
        params["horizon_type"] = horizon_type
    async with get_db() as db:
        result = await db.execute(
            text(f"""
                SELECT * FROM pick_pool_snapshots
                WHERE substr(issued_at, 1, 10) = :date {clause}
                ORDER BY horizon_type ASC, composite_score DESC
                """),  # noqa: S608 - clause は定数リテラルのみ、値は全てバインド  # nosec B608
            params,
        )
        rows = [dict(r._mapping) for r in result]
    return [_parse_row(r) for r in rows]
