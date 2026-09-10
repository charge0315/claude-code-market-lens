"""Celery タスクの結果参照と Redis クライアントの共有.

P1 時点では Redis クライアントの生成のみ。タスク登録 TTL の管理（Market Lens
`task_registry.py` 相当）は非同期バッチを載せるフェーズで移植する。
"""

from __future__ import annotations

import redis.asyncio as redis

from backend.config import settings

_client: redis.Redis | None = None


def get_redis_client() -> redis.Redis:
    """プロセスで 1 つの async Redis クライアントを遅延生成して返す.

    ブローカー URL（DB 番号込み）を共有し、Market Lens とは別 DB 番号で名前空間を分離する。
    """
    global _client
    if _client is None:
        _client = redis.Redis.from_url(settings.celery_broker_url)
    return _client


async def close_redis_client() -> None:
    """シャットダウン時に接続を閉じる."""
    global _client
    if _client is not None:
        await _client.aclose()
        _client = None
