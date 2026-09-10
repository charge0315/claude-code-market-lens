"""ヘルスチェックエンドポイントの検証."""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient


@pytest_asyncio.fixture
async def client(initialized_db: Path) -> AsyncIterator[AsyncClient]:
    """隔離 DB で初期化した ASGI アプリへの HTTP クライアント."""
    from backend.main import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


async def test_liveness_returns_ok(client: AsyncClient) -> None:
    """`/api/health` は依存先を見ず ok と version を返す."""
    res = await client.get("/api/health")
    assert res.status_code == 200
    assert res.json() == {"status": "ok", "version": "0.1.0"}


async def test_dependency_healthcheck_reports_db_ok(client: AsyncClient) -> None:
    """隔離 DB へ接続できるので db=ok。status とコードは checks から導かれる."""
    res = await client.get("/health")
    body = res.json()
    assert body["checks"]["db"] == "ok"
    healthy = all(v == "ok" for v in body["checks"].values())
    assert (res.status_code, body["status"]) == ((200, "healthy") if healthy else (503, "unhealthy"))


async def test_dependency_healthcheck_returns_503_when_redis_down(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Redis 疎通が失敗すると `/health` は 503 で redis=error を返す（DB は ok）."""
    from backend.routers import health

    async def _redis_down() -> bool:
        return False

    monkeypatch.setattr(health, "_check_redis", _redis_down)
    res = await client.get("/health")
    assert res.status_code == 503
    body = res.json()
    assert body["checks"] == {"db": "ok", "redis": "error"}
    assert body["status"] == "unhealthy"


@pytest.mark.parametrize("path", ["/health", "/api/system/health"])
async def test_healthcheck_mounted_at_both_paths(client: AsyncClient, path: str) -> None:
    """`/health` と `/api/system/health` の両方でヘルスチェックへ到達できる."""
    res = await client.get(path)
    assert res.status_code in (200, 503)
    assert "checks" in res.json()
