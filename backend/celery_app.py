"""Celery アプリケーションインスタンス.

学習・決着バッチ・トレンド同期・通知監視・ドリフト検知をプロセス外で回すための基盤。
Market Lens `backend/celery_app.py` の設計を踏襲する:

- Windows では prefork pool が使えないため、ワーカーは `--pool=solo` で起動する:
    .venv/Scripts/celery.exe -A backend.celery_app worker --pool=solo --loglevel=info
- beat スケジュールは UTC 固定で評価されるため、JST 時刻は UTC へ換算して書く（JST は DST なし）。
- Redis は別途起動が必要（`docker run -p 6379:6379 redis` 等）。DB 番号は Alpha Forge 専用。

P1 時点では beat スケジュールは枠のみ（タスク本体は各フェーズで実装）。
"""

from pathlib import Path

from celery import Celery
from celery.schedules import crontab
from dotenv import load_dotenv

# celery 単独プロセス起動時は backend/main.py の load_dotenv() が走らないため、ここで明示的に読む。
load_dotenv(Path(__file__).resolve().parent.parent / ".env")

from backend.config import settings  # noqa: E402

RESULT_EXPIRES_SECONDS = 60 * 60

DEFAULT_QUEUE = "celery"
INTERACTIVE_QUEUE = "interactive"

celery_app = Celery(
    "alpha_forge",
    broker=settings.celery_broker_url,
    backend=settings.celery_result_backend,
    include=["backend.tasks"],
)

# beat スケジュール。時刻は UTC 固定で評価されるため JST は UTC へ換算して書く（JST は DST なし）。
# 方針（`plans/03_システム設計.md` §3.6）: ピック生成 08:50 JST / 決着・評価は夜間 /
# トレンド同期 1 日 4 回。保有監視・フル再学習・昇格ゲートは P5/P7 で追加する。
_BEAT_SCHEDULE: dict[str, dict[str, object]] = {
    "run-picks-mid-term": {
        "task": "backend.tasks.run_picks_task",
        "args": ("mid_term",),
        "schedule": crontab(hour=23, minute=50),  # JST 08:50（寄り付き前）
    },
    "run-picks-short-term": {
        "task": "backend.tasks.run_picks_task",
        "args": ("short_term",),
        "schedule": crontab(hour=23, minute=52),  # JST 08:52（2 分ずらして直列ワーカーの二重占有回避）
    },
    "resolve-pick-outcomes": {
        "task": "backend.tasks.resolve_pick_outcomes_task",
        "schedule": crontab(hour=7, minute=38),  # JST 16:38（大引け後）
    },
    "update-eval-metrics": {
        "task": "backend.tasks.update_eval_metrics_task",
        "schedule": crontab(hour=7, minute=48),  # JST 16:48（決着後）
    },
    "sync-trends": {
        "task": "backend.tasks.sync_trends_task",
        "schedule": crontab(hour="22,1,4,7", minute=13),  # JST 07:13 / 10:13 / 13:13 / 16:13
    },
    "run-drift-check": {
        "task": "backend.tasks.run_drift_check_task",
        "schedule": crontab(hour=18, minute=30, day_of_week="sun"),  # JST 日曜 03:30（深夜・週次）
    },
    "run-promotion-evaluation": {
        "task": "backend.tasks.run_promotion_evaluation_task",
        "schedule": crontab(hour=18, minute=45, day_of_week="sun"),  # JST 日曜 03:45（ドリフト検知の後）
    },
    "run-pool-training": {
        "task": "backend.tasks.run_pool_training_task",
        # JST 毎月1日 04:00（月次。J-Quants 一括バー呼び出しが重いため週次より粗い頻度にする）。
        "schedule": crontab(hour=19, minute=0, day_of_month=1),
    },
    "run-portfolio-monitor": {
        "task": "backend.tasks.run_portfolio_monitor_task",
        # 5分おき常時発火。立会時間外（JST 平日 9:00-15:30 外）はタスク内部で軽い早期 return
        # （`run_signal_scan_task` 等、既存の場中限定タスクと同じ idiom）。
        "schedule": crontab(minute="*/5"),
    },
}

celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    result_expires=RESULT_EXPIRES_SECONDS,
    task_track_started=True,
    timezone="UTC",
    enable_utc=True,
    beat_schedule=_BEAT_SCHEDULE,
    task_default_queue=DEFAULT_QUEUE,
)
