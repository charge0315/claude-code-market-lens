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

# beat スケジュール（枠）。各タスクは対応フェーズで実装し、その時点で有効化する。
# 時刻方針（`plans/03_システム設計.md` §3.6、JST → UTC 換算）:
#   ピック生成 08:50 JST / 保有監視 場中 5 分周期 / 決着・評価・軽量再学習・PSI 夜間 /
#   フル再学習 + 昇格ゲート 週次 / EOD レビュー 16:31 JST。
_BEAT_SCHEDULE: dict[str, dict[str, object]] = {
    # 例（P3 で有効化）: "run-picks-daily": {
    #     "task": "backend.tasks.run_picks_task",
    #     "schedule": crontab(hour=23, minute=50),  # JST 08:50
    # },
}

# 現時点では crontab を実利用しないが、スケジュール追加時に import 済みであることを保つ。
_ = crontab

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
