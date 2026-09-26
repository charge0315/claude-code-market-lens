"""外部 API キー設定 API（`routers/settings.py`）の検証."""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

from backend.services import config_store
from backend.services.llm import model_catalog


@pytest.fixture(autouse=True)
def _no_real_model_catalog(monkeypatch: pytest.MonkeyPatch) -> None:
    """設定APIのテストから公式モデル一覧APIを実際に叩かない（キーが環境にあっても）."""

    async def _empty() -> dict[str, list[str]]:
        return {}

    monkeypatch.setattr(model_catalog, "fetch_all_models", _empty)


async def test_get_llm_providers_uses_fetched_models(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _fetched() -> dict[str, list[str]]:
        return {"gemini": ["gemini-3.8-flash"]}

    monkeypatch.setattr(model_catalog, "fetch_all_models", _fetched)
    from backend.main import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        res = await client.get("/api/settings/llm-providers")

    providers = {p["value"]: p for p in res.json()["data"]["available_providers"]}
    assert providers["gemini"]["model_presets"] == ["gemini-3.8-flash"]
    assert providers["gemini"]["model_source"] == "api"
    assert providers["anthropic"]["model_source"] == "preset"


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


async def test_get_llm_providers_returns_features_and_available_providers() -> None:
    from backend.main import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        res = await client.get("/api/settings/llm-providers")

    body = res.json()
    assert body["success"] is True
    assert body["data"]["restart_required"] is False
    features = {f["feature"]: f for f in body["data"]["features"]}
    assert set(features) == {"stock_pick", "portfolio_signal", "eod_review", "trend_analyzer"}
    provider_values = {p["value"] for p in body["data"]["available_providers"]}
    assert provider_values == {"anthropic", "openai", "gemini"}


async def test_patch_llm_providers_persists_and_reports_restart_required(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    env_path = tmp_path / ".env"
    env_path.write_text("FOO=bar\n", encoding="utf-8")
    monkeypatch.setattr(config_store, "_ENV_PATH", env_path)

    from backend.main import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        res = await client.patch(
            "/api/settings/llm-providers",
            json={"feature": "stock_pick", "primary_provider": "openai", "shadow_providers": ["anthropic", "gemini"]},
        )

    body = res.json()
    assert body["success"] is True
    assert body["data"]["restart_required"] is True
    features = {f["feature"]: f for f in body["data"]["features"]}
    assert features["stock_pick"]["primary_provider"] == "openai"
    assert features["stock_pick"]["shadow_providers"] == ["anthropic", "gemini"]
    saved = env_path.read_text(encoding="utf-8").splitlines()
    assert "LLM_PROVIDER_STOCK_PICK=openai" in saved
    assert "LLM_SHADOW_PROVIDERS_STOCK_PICK=anthropic,gemini" in saved
    # 他機能の設定は変更されない。
    assert features["portfolio_signal"]["primary_provider"] == "anthropic"


async def test_patch_llm_providers_without_fields_returns_400() -> None:
    from backend.main import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        res = await client.patch("/api/settings/llm-providers", json={"feature": "eod_review"})

    assert res.status_code == 400


async def test_get_llm_providers_includes_model_presets_and_current_models(monkeypatch: pytest.MonkeyPatch) -> None:
    # 実際の `.env` に機能別のモデル上書きがあると既定値と一致しなくなるため消しておく。
    monkeypatch.delenv("LLM_MODEL_STOCK_PICK_ANTHROPIC", raising=False)
    from backend.main import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        res = await client.get("/api/settings/llm-providers")

    body = res.json()
    providers = {p["value"]: p for p in body["data"]["available_providers"]}
    assert "claude-opus-5" in providers["anthropic"]["model_presets"]
    assert providers["anthropic"]["default_model"]
    features = {f["feature"]: f for f in body["data"]["features"]}
    assert features["stock_pick"]["models"]["anthropic"] == providers["anthropic"]["default_model"]


async def test_patch_llm_providers_updates_model_override(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    env_path = tmp_path / ".env"
    env_path.write_text("FOO=bar\n", encoding="utf-8")
    monkeypatch.setattr(config_store, "_ENV_PATH", env_path)

    from backend.main import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        res = await client.patch(
            "/api/settings/llm-providers",
            json={"feature": "stock_pick", "models": {"anthropic": "claude-opus-5"}},
        )

    body = res.json()
    assert body["success"] is True
    features = {f["feature"]: f for f in body["data"]["features"]}
    assert features["stock_pick"]["models"]["anthropic"] == "claude-opus-5"
    # 上書きしていないプロバイダはプロバイダ既定値のまま。
    assert features["stock_pick"]["models"]["gemini"] != "claude-opus-5"
    saved = env_path.read_text(encoding="utf-8").splitlines()
    assert "LLM_MODEL_STOCK_PICK_ANTHROPIC=claude-opus-5" in saved
