"""`services/db/notification_db`（`notifications` / `push_subscriptions` CRUD）の検証."""

from __future__ import annotations

from datetime import datetime as real_datetime
from pathlib import Path

import pytest

from backend.services.db import notification_db
from backend.services.db.notification_db import (
    insert_notification,
    list_active_subscriptions,
    list_notifications,
    list_notifications_since,
    mark_read,
    revoke_subscription,
    upsert_subscription,
)


def _freeze(monkeypatch: pytest.MonkeyPatch, iso: str) -> None:
    """`created_at` の秒単位丸めによる同一秒衝突を避けるため `datetime.now` を固定する."""
    frozen = real_datetime.fromisoformat(iso)

    class _Frozen(real_datetime):
        @classmethod
        def now(cls, tz: object = None) -> real_datetime:  # type: ignore[override]  # noqa: ARG003
            return frozen

    monkeypatch.setattr(notification_db, "datetime", _Frozen)


async def test_insert_notification_dedupes_same_run_date_ticker_kind(migrated_db: Path) -> None:
    first = await insert_notification(ticker="7203", kind="trim", body="{}", run_date="2026-06-02")
    second = await insert_notification(ticker="7203", kind="trim", body="{}", run_date="2026-06-02")

    assert first is not None
    assert second is None
    assert len(await list_notifications()) == 1


async def test_insert_notification_allows_different_kind_same_day(migrated_db: Path) -> None:
    first = await insert_notification(ticker="7203", kind="trim", body="{}", run_date="2026-06-02")
    second = await insert_notification(ticker="7203", kind="add", body="{}", run_date="2026-06-02")

    assert first is not None
    assert second is not None
    assert len(await list_notifications()) == 2


async def test_list_notifications_unread_only_filters(migrated_db: Path) -> None:
    notification_id = await insert_notification(ticker="7203", kind="trim", body="{}", run_date="2026-06-02")
    assert notification_id is not None
    await insert_notification(ticker="6758", kind="add", body="{}", run_date="2026-06-02")
    await mark_read(notification_id)

    unread = await list_notifications(unread_only=True)
    assert len(unread) == 1
    assert unread[0]["ticker"] == "6758"


async def test_list_notifications_since_returns_newer_only_in_ascending_order(
    migrated_db: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _freeze(monkeypatch, "2026-06-02T09:00:00+09:00")
    first_id = await insert_notification(ticker="7203", kind="trim", body="{}", run_date="2026-06-01")
    assert first_id is not None
    watermark = "2026-06-02T09:00:00+09:00"

    # 起点時刻ちょうどの通知（自分自身）は含まれない（`>` 比較）。
    assert await list_notifications_since(watermark) == []

    _freeze(monkeypatch, "2026-06-02T09:00:05+09:00")
    await insert_notification(ticker="6758", kind="add", body="{}", run_date="2026-06-03")
    rows_after = await list_notifications_since(watermark)
    assert [r["ticker"] for r in rows_after] == ["6758"]


async def test_mark_read_unknown_returns_none(migrated_db: Path) -> None:
    assert await mark_read("does-not-exist") is None


async def test_push_subscription_upsert_list_and_revoke(migrated_db: Path) -> None:
    await upsert_subscription(endpoint="https://push.example/a", p256dh="p1", auth="a1", user_agent="UA1")

    active = await list_active_subscriptions()
    assert len(active) == 1
    assert active[0]["p256dh"] == "p1"

    # 同一 endpoint への再登録は鍵を更新する（upsert）。
    await upsert_subscription(endpoint="https://push.example/a", p256dh="p2", auth="a2", user_agent="UA2")
    active_after_upsert = await list_active_subscriptions()
    assert len(active_after_upsert) == 1
    assert active_after_upsert[0]["p256dh"] == "p2"

    ok = await revoke_subscription("https://push.example/a")
    assert ok is True
    assert await list_active_subscriptions() == []


async def test_revoke_unknown_subscription_returns_false(migrated_db: Path) -> None:
    assert await revoke_subscription("https://push.example/unknown") is False
