"""通知 API（`routers/notify.py`）と WS ライブ配信の検証."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

from backend import config
from backend.routers import notify as notify_router_module
from backend.services.db.notification_db import insert_notification


async def test_get_notifications_and_mark_read_flow(migrated_db: Path) -> None:
    notification_id = await insert_notification(ticker="7203", kind="trim", body="{}", run_date="2026-06-02")
    assert notification_id is not None

    from backend.main import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        list_res = await client.get("/api/notify/notifications")
        assert list_res.json()["data"][0]["notification_id"] == notification_id

        unread_res = await client.get("/api/notify/notifications?unread_only=true")
        assert len(unread_res.json()["data"]) == 1

        read_res = await client.patch(f"/api/notify/notifications/{notification_id}/read")
        assert read_res.json()["data"]["read_at"] is not None

        unread_after = await client.get("/api/notify/notifications?unread_only=true")
        assert unread_after.json()["data"] == []


async def test_mark_read_unknown_returns_404(migrated_db: Path) -> None:
    from backend.main import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        res = await client.patch("/api/notify/notifications/does-not-exist/read")
    assert res.status_code == 404


async def test_vapid_key_endpoint_returns_configured_public_key(
    migrated_db: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    new_settings = config.settings.model_copy(update={"vapid_public_key": "test-public-key"})
    monkeypatch.setattr(notify_router_module, "settings", new_settings)

    from backend.main import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        res = await client.get("/api/notify/vapid-key")
    assert res.json()["data"]["public_key"] == "test-public-key"


async def test_subscribe_then_unsubscribe_flow(migrated_db: Path) -> None:
    from backend.main import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        sub_res = await client.post(
            "/api/notify/subscribe",
            json={"endpoint": "https://push.example/a", "p256dh": "p", "auth": "a", "user_agent": "UA"},
        )
        assert sub_res.json()["data"]["subscribed"] is True

        unsub_res = await client.post("/api/notify/unsubscribe", json={"endpoint": "https://push.example/a"})
        assert unsub_res.json()["data"]["unsubscribed"] is True

        # 既に revoked=1 でも endpoint 自体は存在するため、再解除は冪等に True を返す。
        unsub_again = await client.post("/api/notify/unsubscribe", json={"endpoint": "https://push.example/a"})
        assert unsub_again.json()["data"]["unsubscribed"] is True

        unsub_unknown = await client.post("/api/notify/unsubscribe", json={"endpoint": "https://push.example/unknown"})
        assert unsub_unknown.json()["data"]["unsubscribed"] is False


def test_notifications_ws_streams_newly_inserted_notification(
    migrated_db: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """WS はポーリングで新規行を検知する。real DB ファイルへの直接 INSERT で新規発生を模す
    （非同期エンジンを介さない同期 sqlite3 接続 — TestClient は別スレッドの別イベントループで
    ASGI アプリを動かすため、pytest 側の async fixture が張る SQLAlchemy 非同期エンジンとは
    別ループになり共有できない）。
    """
    monkeypatch.setattr(notify_router_module, "_WS_POLL_INTERVAL_SECONDS", 0.05)

    from fastapi.testclient import TestClient

    from backend.main import app

    with TestClient(app) as client, client.websocket_connect("/ws/notifications") as ws:
        conn = sqlite3.connect(migrated_db)
        conn.execute("""
            INSERT INTO notifications (notification_id, run_date, ticker, kind, channel, body, created_at)
            VALUES ('n1', '2026-06-02', '7203', 'trim', 'in_app', '{}', '2099-01-01T00:00:00+09:00')
            """)
        conn.commit()
        conn.close()

        msg = ws.receive_json()

    assert msg["notification_id"] == "n1"
    assert msg["ticker"] == "7203"
    assert msg["kind"] == "trim"
