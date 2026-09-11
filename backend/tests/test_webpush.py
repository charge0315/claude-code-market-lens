"""`services/notify/webpush`（Web Push 配信）の検証."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

import pytest
from pywebpush import WebPushException

from backend import config
from backend.services.db.notification_db import list_active_subscriptions, upsert_subscription
from backend.services.notify import webpush


def _configure_vapid(monkeypatch: pytest.MonkeyPatch, *, public: str = "pub", private: str = "priv") -> None:
    new_settings = config.settings.model_copy(
        update={"vapid_public_key": public, "vapid_private_key": private, "vapid_subject": "mailto:test@example.com"}
    )
    monkeypatch.setattr(webpush, "settings", new_settings)


class _FakeResponse:
    def __init__(self, status_code: int) -> None:
        self.status_code = status_code


async def test_send_to_all_returns_zero_when_vapid_unconfigured(
    migrated_db: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _configure_vapid(monkeypatch, public="", private="")
    await upsert_subscription(endpoint="https://push.example/a", p256dh="p", auth="a", user_agent=None)

    sent = await webpush.send_to_all(title="t", body="b")

    assert sent == 0


async def test_send_to_all_sends_to_every_active_subscription(
    migrated_db: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _configure_vapid(monkeypatch)
    await upsert_subscription(endpoint="https://push.example/a", p256dh="p1", auth="a1", user_agent=None)
    await upsert_subscription(endpoint="https://push.example/b", p256dh="p2", auth="a2", user_agent=None)

    calls: list[str] = []

    def fake_send_one(sub: dict[str, object], _payload: str) -> Literal["ok", "revoke", "error"]:
        calls.append(str(sub["endpoint"]))
        return "ok"

    monkeypatch.setattr(webpush, "_send_one", fake_send_one)

    sent = await webpush.send_to_all(title="t", body="b", data={"k": "v"})

    assert sent == 2
    assert set(calls) == {"https://push.example/a", "https://push.example/b"}


async def test_send_to_all_revokes_subscription_on_410(migrated_db: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _configure_vapid(monkeypatch)
    await upsert_subscription(endpoint="https://push.example/gone", p256dh="p", auth="a", user_agent=None)

    def fake_send_one(_sub: dict[str, object], _payload: str) -> Literal["ok", "revoke", "error"]:
        return "revoke"

    monkeypatch.setattr(webpush, "_send_one", fake_send_one)

    sent = await webpush.send_to_all(title="t", body="b")

    assert sent == 0
    assert await list_active_subscriptions() == []


def test_send_one_maps_webpush_exception_status_to_revoke(monkeypatch: pytest.MonkeyPatch) -> None:
    _configure_vapid(monkeypatch)

    def raise_410(**_kwargs: object) -> None:
        raise WebPushException("gone", response=_FakeResponse(410))

    monkeypatch.setattr(webpush, "webpush", raise_410)

    result = webpush._send_one({"endpoint": "e", "p256dh": "p", "auth": "a"}, "{}")

    assert result == "revoke"


def test_send_one_returns_error_for_other_failures(monkeypatch: pytest.MonkeyPatch) -> None:
    _configure_vapid(monkeypatch)

    def raise_500(**_kwargs: object) -> None:
        raise WebPushException("boom", response=_FakeResponse(500))

    monkeypatch.setattr(webpush, "webpush", raise_500)

    result = webpush._send_one({"endpoint": "e", "p256dh": "p", "auth": "a"}, "{}")

    assert result == "error"
