"""外部 API キー設定 API（`routers/settings.py`）の検証."""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

from backend.services import config_store


async def test_get_api_keys_returns_masked_status(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-xxxxxxxxxx1234")
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)

    from backend.main import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        res = await client.get("/api/settings/api-keys")

    body = res.json()
    assert body["success"] is True
    assert body["data"]["restart_required"] is False
    rows = {r["key"]: r for r in body["data"]["keys"]}
    assert rows["anthropic_api_key"]["configured"] is True
    assert "sk-ant" not in rows["anthropic_api_key"]["masked_value"]  # 生値の先頭は絶対に出さない
    assert rows["anthropic_api_key"]["masked_value"].endswith("1234")
    assert rows["gemini_api_key"]["configured"] is False


async def test_patch_api_keys_persists_and_reports_restart_required(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    env_path = tmp_path / ".env"
    env_path.write_text("FOO=bar\n", encoding="utf-8")
    monkeypatch.setattr(config_store, "_ENV_PATH", env_path)
    monkeypatch.setenv("GEMINI_API_KEY", os.environ.get("GEMINI_API_KEY", ""))

    from backend.main import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        res = await client.patch("/api/settings/api-keys", json={"gemini_api_key": "gm-new-key"})

    body = res.json()
    assert body["success"] is True
    assert body["data"]["restart_required"] is True
    rows = {r["key"]: r for r in body["data"]["keys"]}
    assert rows["gemini_api_key"]["configured"] is True
    assert "GEMINI_API_KEY=gm-new-key" in env_path.read_text(encoding="utf-8").splitlines()


async def test_patch_api_keys_without_fields_returns_400() -> None:
    from backend.main import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        res = await client.patch("/api/settings/api-keys", json={})

    assert res.status_code == 400


async def test_patch_api_keys_rejects_newline_value(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    env_path = tmp_path / ".env"
    env_path.write_text("", encoding="utf-8")
    monkeypatch.setattr(config_store, "_ENV_PATH", env_path)

    from backend.main import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        res = await client.patch("/api/settings/api-keys", json={"jquants_api_key": "bad\nvalue"})

    assert res.status_code == 400
