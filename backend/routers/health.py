"""DB / Redis 疎通を含む依存先ヘルスチェック.

Market Lens `backend/routers/health.py` から移植。API プロセスの生存だけでなく、
DB・Redis への実接続を確認し、いずれか失敗で 503 を返す。監視 / ロードバランサの
プローブは Bearer トークンを持たないため認証を要求しない。未認証応答に内部構成の
手がかりを与えないよう、レスポンスには正常 / 異常のみを含める。
"""

from __future__ import annotations

import asyncio
import logging

import redis.exceptions
from fastapi import APIRouter, Response
from sqlalchemy import text

from backend.models.health import HealthCheckResponse
from backend.services import task_registry
from backend.services.db.database import get_db

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/health", tags=["health"])

_DB_CHECK_TIMEOUT_SECONDS = 2.0
_REDIS_PING_TIMEOUT_SECONDS = 2.0


async def _check_db() -> bool:
    """DB への疎通を軽量クエリで確認する（詳細はログのみ）."""
    try:
        async with asyncio.timeout(_DB_CHECK_TIMEOUT_SECONDS):
            async with get_db() as db:
                await db.execute(text("SELECT 1"))
    except Exception as e:  # noqa: BLE001 — 疎通確認は全例外を「異常」に畳んで良い
        logger.warning("ヘルスチェック: DB接続に失敗しました: %s", e)
        return False
    return True


async def _check_redis() -> bool:
    """Redis への疎通を PING で確認する（詳細はログのみ）."""
    try:
        await asyncio.wait_for(task_registry.get_redis_client().ping(), timeout=_REDIS_PING_TIMEOUT_SECONDS)
    except (TimeoutError, redis.exceptions.RedisError) as e:
        logger.warning("ヘルスチェック: Redis接続に失敗しました: %s", e)
        return False
    return True


@router.get("", response_model=HealthCheckResponse, summary="DB/Redis疎通を含むヘルスチェック")
async def health_check(response: Response) -> HealthCheckResponse:
    """DB・Redis へ実接続を試み、いずれか失敗なら 503 を返す（疎通確認は並行実行）."""
    db_ok, redis_ok = await asyncio.gather(_check_db(), _check_redis())
    checks = {"db": "ok" if db_ok else "error", "redis": "ok" if redis_ok else "error"}
    is_healthy = db_ok and redis_ok
    response.status_code = 200 if is_healthy else 503
    return HealthCheckResponse(status="healthy" if is_healthy else "unhealthy", checks=checks)
