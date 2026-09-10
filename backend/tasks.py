"""Celery タスク定義.

`celery -A backend.celery_app worker` はこのモジュールを include して @task を登録する。
P1 時点では疎通確認用の `ping` のみ。学習 / 決着 / 通知 / ドリフトの各タスクは
`plans/04_タスクリスト.md` の対応フェーズで追加する。
"""

from __future__ import annotations

from backend.celery_app import celery_app


@celery_app.task(name="backend.tasks.ping")
def ping() -> str:
    """ワーカー疎通確認用の最小タスク."""
    return "pong"
