"""Celery タスク定義.

`celery -A backend.celery_app worker` はこのモジュールを include して @task を登録する。
非同期のコアロジックは `asyncio.run()` でラップして呼ぶ（Celery ワーカーは FastAPI の
イベントループを共有しない）。beat スケジュールは `celery_app._BEAT_SCHEDULE` で一元管理する
（手動 `.delay()` 投入はしない）。
"""

from __future__ import annotations

import asyncio
import logging

from backend.celery_app import celery_app

logger = logging.getLogger(__name__)


@celery_app.task(name="backend.tasks.ping")
def ping() -> str:
    """ワーカー疎通確認用の最小タスク."""
    return "pong"


@celery_app.task(name="backend.tasks.run_picks_task")
def run_picks_task(horizon_type: str) -> dict[str, object]:
    """指定系統（mid_term / short_term）のピックを生成し台帳化する（JST 08:50）."""
    from backend.services.picks.pipeline import run_picks

    result = asyncio.run(run_picks(horizon_type))
    return {"status": result.status, "picks": len(result.picks), "rejected": len(result.rejected)}


@celery_app.task(name="backend.tasks.resolve_pick_outcomes_task")
def resolve_pick_outcomes_task() -> dict[str, int]:
    """未決着ピックを古い順に解決して `pick_outcomes` へ書き込む（夜間）."""
    from backend.services.ledger.outcome_resolver import resolve_pending

    s = asyncio.run(resolve_pending(max_picks=20))
    return {
        "resolved_picks": s.resolved_picks,
        "written_outcomes": s.written_outcomes,
        "unfilled": s.unfilled,
        "failed": s.failed,
    }


@celery_app.task(name="backend.tasks.update_eval_metrics_task")
def update_eval_metrics_task() -> dict[str, object]:
    """決着後に評価指標（較正 / IC / 成績）を再集計して `eval_snapshots` へ追記する（夜間）."""
    from backend.services.ledger.eval_service import run_eval_batch

    return {"scopes": list(asyncio.run(run_eval_batch()))}


@celery_app.task(name="backend.tasks.sync_trends_task")
def sync_trends_task() -> dict[str, object]:
    """Trend Tracking Agent を同期する（1 日 4 回。TTL 3h 内は再利用）."""
    from backend.services.data.trend.sync_service import sync_trends

    snap = asyncio.run(sync_trends())
    return {"status": snap.status, "trends": len(snap.trends), "signals": snap.signal_count}
