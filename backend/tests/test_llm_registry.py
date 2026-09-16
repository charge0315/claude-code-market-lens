"""`services/llm/registry.py`（機能別プロバイダ解決）の検証."""

from __future__ import annotations

import pytest

from backend.services.llm import registry as reg


def _settings_with(**overrides: object) -> object:
    import backend.config as config_module

    return config_module.settings.model_copy(update=overrides)


def test_resolve_feature_provider_reads_per_feature_setting(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        reg,
        "settings",
        _settings_with(llm_provider_stock_pick="openai", llm_provider_eod_review="gemini"),
    )
    assert reg.resolve_feature_provider("stock_pick").provider_id == "openai"
    assert reg.resolve_feature_provider("eod_review").provider_id == "gemini"
    assert reg.resolve_feature_provider("portfolio_signal").provider_id == "anthropic"  # 既定のまま


def test_resolve_shadow_providers_excludes_primary_duplicate(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        reg,
        "settings",
        _settings_with(
            llm_provider_stock_pick="anthropic",
            llm_shadow_providers_stock_pick=["anthropic", "gemini"],
        ),
    )
    from backend.services.gemini_client import GeminiClient

    monkeypatch.setattr(GeminiClient, "is_configured", property(lambda self: True))

    providers = reg.resolve_shadow_providers("stock_pick")
    assert [p.provider_id for p in providers] == ["gemini"]


def test_resolve_shadow_providers_excludes_unconfigured(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        reg,
        "settings",
        _settings_with(llm_shadow_providers_stock_pick=["openai", "gemini"]),
    )
    from backend.services.gemini_client import gemini_client
    from backend.services.openai_client import openai_client

    monkeypatch.setattr(type(openai_client), "is_configured", property(lambda self: False))
    monkeypatch.setattr(type(gemini_client), "is_configured", property(lambda self: True))

    providers = reg.resolve_shadow_providers("stock_pick")
    assert [p.provider_id for p in providers] == ["gemini"]


def test_resolve_shadow_providers_returns_multiple_when_all_configured(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        reg,
        "settings",
        _settings_with(llm_shadow_providers_stock_pick=["openai", "gemini"]),
    )
    from backend.services.gemini_client import gemini_client
    from backend.services.openai_client import openai_client

    monkeypatch.setattr(type(openai_client), "is_configured", property(lambda self: True))
    monkeypatch.setattr(type(gemini_client), "is_configured", property(lambda self: True))

    providers = reg.resolve_shadow_providers("stock_pick")
    assert {p.provider_id for p in providers} == {"openai", "gemini"}


def test_resolve_shadow_providers_empty_when_none_configured(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(reg, "settings", _settings_with(llm_shadow_providers_eod_review=["openai"]))
    from backend.services.openai_client import openai_client

    monkeypatch.setattr(type(openai_client), "is_configured", property(lambda self: False))

    assert reg.resolve_shadow_providers("eod_review") == []


def test_resolve_model_falls_back_to_provider_default_when_no_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(reg, "settings", _settings_with(anthropic_model="claude-sonnet-5"))
    assert reg.resolve_model("stock_pick", "anthropic") == "claude-sonnet-5"


def test_resolve_model_prefers_feature_provider_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        reg,
        "settings",
        _settings_with(anthropic_model="claude-sonnet-5", llm_model_stock_pick_anthropic="claude-opus-5"),
    )
    assert reg.resolve_model("stock_pick", "anthropic") == "claude-opus-5"
    # 上書きは指定した機能にのみ適用され、他機能はプロバイダ既定値のまま。
    assert reg.resolve_model("portfolio_signal", "anthropic") == "claude-sonnet-5"


def test_resolve_model_override_is_independent_per_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        reg,
        "settings",
        _settings_with(
            gemini_model="gemini-2.5-pro",
            llm_model_stock_pick_gemini="gemini-2.5-flash",
        ),
    )
    assert reg.resolve_model("stock_pick", "gemini") == "gemini-2.5-flash"
    assert reg.resolve_model("stock_pick", "openai") != "gemini-2.5-flash"
