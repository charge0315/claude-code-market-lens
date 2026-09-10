"""四季報スタブの検証（SHIKIHO_ENABLED=false の間は常に None）."""

from __future__ import annotations

import pytest

from backend import config
from backend.services.data import shikiho


async def test_returns_none_when_disabled() -> None:
    assert await shikiho.get_shikiho("7203") is None


async def test_returns_none_even_when_enabled_without_datasource(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """データソース未実装のため、フラグを立てても None（警告ログのみ）."""
    enabled = config.settings.model_copy(update={"shikiho_enabled": True})
    monkeypatch.setattr(shikiho, "settings", enabled)
    monkeypatch.setattr(shikiho, "_warned", False)
    assert await shikiho.get_shikiho("7203") is None
