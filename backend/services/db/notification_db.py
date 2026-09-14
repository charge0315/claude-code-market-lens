"""`notifications` / `push_subscriptions` の読み書き（SQLAlchemy async）.

`plans/03_システム設計` §2.6。重複防止は DB の `(run_date, ticker, kind)` 一意制約に委譲する
（Market Lens `notification_service.py` の insert/dedupe パターンを踏襲）。`channel` 列は常に
DB 既定値 `in_app` のまま書き込む — Web Push 配信は通知レコードとは独立した副作用（送達の
成否で通知一覧の見え方が変わるべきではない）として `services/notify/webpush.py` が担う。
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from backend.services.db.database import get_db
from backend.services.jst_time import JST, today_jst


async def insert_notification(*, ticker: str, kind: str, body: str, run_date: str | None = None) -> str | None:
    """通知を1件追加する。同日・同銘柄・同 kind が既に存在する場合は None（重複防止）."""
    notification_id = str(uuid.uuid4())
    now = datetime.now(JST).isoformat(timespec="seconds")
    try:
        async with get_db() as db:
            await db.execute(
                text("""
                    INSERT INTO notifications (notification_id, run_date, ticker, kind, body, created_at)
                    VALUES (:notification_id, :run_date, :ticker, :kind, :body, :created_at)
                    """),
                {
                    "notification_id": notification_id,
                    "run_date": run_date or today_jst(),
                    "ticker": ticker,
                    "kind": kind,
                    "body": body,
                    "created_at": now,
                },
            )
    except IntegrityError:
        return None
    return notification_id


async def list_notifications(*, unread_only: bool = False, limit: int = 200) -> list[dict[str, object]]:
    """通知一覧を新しい順で返す."""
    clause = "WHERE read_at IS NULL" if unread_only else ""
    async with get_db() as db:
        query = f"SELECT * FROM notifications {clause} ORDER BY created_at DESC LIMIT :limit"  # noqa: S608 - clause は定数のみ  # nosec B608
        result = await db.execute(text(query), {"limit": limit})
        return [dict(r._mapping) for r in result]


async def list_notifications_since(created_at: str, *, limit: int = 100) -> list[dict[str, object]]:
    """指定時刻より後に作成された通知を古い順で返す（WS ポーリング用）."""
    async with get_db() as db:
        result = await db.execute(
            text("SELECT * FROM notifications WHERE created_at > :created_at ORDER BY created_at ASC LIMIT :limit"),
            {"created_at": created_at, "limit": limit},
        )
        return [dict(r._mapping) for r in result]


async def mark_read(notification_id: str) -> dict[str, object] | None:
    """既読にする。対象行が無ければ None."""
    now = datetime.now(JST).isoformat(timespec="seconds")
    async with get_db() as db:
        result = await db.execute(
            text("UPDATE notifications SET read_at = :read_at WHERE notification_id = :notification_id"),
            {"read_at": now, "notification_id": notification_id},
        )
        if result.rowcount == 0:
            return None
        row = await db.execute(
            text("SELECT * FROM notifications WHERE notification_id = :notification_id"),
            {"notification_id": notification_id},
        )
        found = row.first()
        return dict(found._mapping) if found is not None else None


async def upsert_subscription(*, endpoint: str, p256dh: str, auth: str, user_agent: str | None) -> None:
    """Web Push 購読を登録する（同一 endpoint は鍵を更新し `revoked` を解除）."""
    now = datetime.now(JST).isoformat(timespec="seconds")
    async with get_db() as db:
        await db.execute(
            text("""
                INSERT INTO push_subscriptions (endpoint, p256dh, auth, created_at, user_agent, revoked)
                VALUES (:endpoint, :p256dh, :auth, :created_at, :user_agent, 0)
                ON CONFLICT(endpoint) DO UPDATE SET
                    p256dh = excluded.p256dh, auth = excluded.auth,
                    user_agent = excluded.user_agent, revoked = 0
                """),
            {"endpoint": endpoint, "p256dh": p256dh, "auth": auth, "created_at": now, "user_agent": user_agent},
        )


async def revoke_subscription(endpoint: str) -> bool:
    """購読を無効化する（配信対象から除外）。対象行が無ければ False."""
    async with get_db() as db:
        result = await db.execute(
            text("UPDATE push_subscriptions SET revoked = 1 WHERE endpoint = :endpoint"),
            {"endpoint": endpoint},
        )
        return result.rowcount > 0


async def list_active_subscriptions() -> list[dict[str, object]]:
    """無効化されていない購読を全件返す."""
    async with get_db() as db:
        result = await db.execute(text("SELECT * FROM push_subscriptions WHERE revoked = 0"))
        return [dict(r._mapping) for r in result]
