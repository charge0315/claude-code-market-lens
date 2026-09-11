"""`services/notify/notification_service.notify_signal` の検証."""

from __future__ import annotations

from pathlib import Path

import pytest

from backend.services.db.notification_db import list_notifications
from backend.services.notify import notification_service as svc


async def test_notify_signal_skips_hold_action(migrated_db: Path) -> None:
    notification_id = await svc.notify_signal(
        symbol="7203", action="hold", stop=900.0, target=1100.0, confidence=60.0, rationale="堅調"
    )

    assert notification_id is None
    assert await list_notifications() == []


@pytest.mark.parametrize("action", ["trim", "stop_loss", "add"])
async def test_notify_signal_persists_notification_for_actionable_signals(
    migrated_db: Path, monkeypatch: pytest.MonkeyPatch, action: str
) -> None:
    sent_data: list[dict[str, object] | None] = []

    async def fake_send_to_all(*, title: str, body: str, data: dict[str, object] | None = None) -> int:
        sent_data.append(data)
        return 1

    monkeypatch.setattr(svc.webpush, "send_to_all", fake_send_to_all)

    notification_id = await svc.notify_signal(
        symbol="7203", action=action, stop=900.0, target=1100.0, confidence=60.0, rationale="根拠テキスト"
    )

    assert notification_id is not None
    rows = await list_notifications()
    assert len(rows) == 1
    assert rows[0]["kind"] == action
    assert rows[0]["ticker"] == "7203"
    assert len(sent_data) == 1
    data = sent_data[0]
    assert data is not None
    assert data["notification_id"] == notification_id


async def test_notify_signal_dedupes_same_day_symbol_action(migrated_db: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_send_to_all(**_kwargs: object) -> int:
        return 0

    monkeypatch.setattr(svc.webpush, "send_to_all", fake_send_to_all)

    first = await svc.notify_signal(
        symbol="7203", action="trim", stop=900.0, target=1100.0, confidence=60.0, rationale="1回目"
    )
    second = await svc.notify_signal(
        symbol="7203", action="trim", stop=910.0, target=1090.0, confidence=55.0, rationale="2回目"
    )

    assert first is not None
    assert second is None
    assert len(await list_notifications()) == 1
