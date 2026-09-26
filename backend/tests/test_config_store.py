"""`services/config_store.py`（外部 API キーのマスク表示・.env 永続化）の検証."""

from __future__ import annotations

import os
from pathlib import Path
from typing import cast

import pytest

from backend.services import config_store


def _models(row: dict[str, object]) -> dict[str, str]:
    return cast("dict[str, str]", row["models"])


def test_mask_keeps_only_last_four_chars() -> None:
    value = "sk-ant-abcdefgh1234"
    assert config_store._mask(value) == "•" * (len(value) - 4) + "1234"


def test_mask_short_value_is_fully_masked() -> None:
    assert config_store._mask("abc") == "•••"


def test_get_api_key_status_reflects_os_environ(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-xxxxxxxxxx1234")
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.setenv("JQUANTS_API_KEY", "jq-key-5678")

    rows = {row["key"]: row for row in config_store.get_api_key_status()}

    assert rows["anthropic_api_key"]["configured"] is True
    masked = rows["anthropic_api_key"]["masked_value"]
    assert isinstance(masked, str) and masked.endswith("1234")
    assert rows["gemini_api_key"]["configured"] is False
    assert rows["gemini_api_key"]["masked_value"] is None
    assert rows["jquants_api_key"]["configured"] is True


def test_update_env_keys_replaces_existing_line(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    env_path = tmp_path / ".env"
    env_path.write_text("FOO=bar\nANTHROPIC_API_KEY=old-value\nBAZ=qux\n", encoding="utf-8")
    monkeypatch.setattr(config_store, "_ENV_PATH", env_path)
    # update_env_keys は os.environ も直接書き換えるため、monkeypatch に現在値を登録して
    # テスト終了時に元へ戻す（実プロセスの ANTHROPIC_API_KEY を汚染しない）。
    monkeypatch.setenv("ANTHROPIC_API_KEY", os.environ.get("ANTHROPIC_API_KEY", ""))

    config_store.update_env_keys({"ANTHROPIC_API_KEY": "new-value"})

    content = env_path.read_text(encoding="utf-8")
    lines = content.splitlines()
    assert "ANTHROPIC_API_KEY=new-value" in lines
    assert "FOO=bar" in lines
    assert "BAZ=qux" in lines
    assert lines.index("FOO=bar") < lines.index("ANTHROPIC_API_KEY=new-value") < lines.index("BAZ=qux")
    assert os.environ.get("ANTHROPIC_API_KEY") == "new-value"


def test_update_env_keys_appends_when_missing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    env_path = tmp_path / ".env"
    env_path.write_text("FOO=bar\n", encoding="utf-8")
    monkeypatch.setattr(config_store, "_ENV_PATH", env_path)
    monkeypatch.setenv("GEMINI_API_KEY", os.environ.get("GEMINI_API_KEY", ""))

    config_store.update_env_keys({"GEMINI_API_KEY": "gm-key"})

    content = env_path.read_text(encoding="utf-8")
    assert "GEMINI_API_KEY=gm-key" in content.splitlines()


def test_update_env_keys_creates_file_when_absent(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    env_path = tmp_path / ".env"
    monkeypatch.setattr(config_store, "_ENV_PATH", env_path)
    monkeypatch.setenv("JQUANTS_API_KEY", os.environ.get("JQUANTS_API_KEY", ""))

    config_store.update_env_keys({"JQUANTS_API_KEY": "jq-new"})

    assert env_path.read_text(encoding="utf-8").splitlines() == ["JQUANTS_API_KEY=jq-new"]


def test_update_env_keys_rejects_newline(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    env_path = tmp_path / ".env"
    env_path.write_text("", encoding="utf-8")
    monkeypatch.setattr(config_store, "_ENV_PATH", env_path)

    with pytest.raises(ValueError, match="改行"):
        config_store.update_env_keys({"ANTHROPIC_API_KEY": "bad\nvalue"})


def test_env_name_for_field_returns_none_for_unknown() -> None:
    assert config_store.env_name_for_field("unknown_field") is None
    assert config_store.env_name_for_field("gemini_api_key") == "GEMINI_API_KEY"


def test_get_llm_provider_options_reflects_api_key_status(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-x")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)

    options = {o["value"]: o for o in config_store.get_llm_provider_options()}

    assert options["anthropic"]["configured"] is True
    assert options["openai"]["configured"] is False
    assert options["gemini"]["configured"] is False


def test_get_llm_provider_settings_defaults_match_current_behavior(monkeypatch: pytest.MonkeyPatch) -> None:
    """未設定時の既定値は導入前の挙動（公式=anthropic、shadow=stock_pick/portfolio_signalのみgemini）と一致する."""
    for env_name in (
        "LLM_PROVIDER_STOCK_PICK",
        "LLM_PROVIDER_PORTFOLIO_SIGNAL",
        "LLM_PROVIDER_EOD_REVIEW",
        "LLM_PROVIDER_TREND_ANALYZER",
        "LLM_SHADOW_PROVIDERS_STOCK_PICK",
        "LLM_SHADOW_PROVIDERS_PORTFOLIO_SIGNAL",
        "LLM_SHADOW_PROVIDERS_EOD_REVIEW",
        "LLM_SHADOW_PROVIDERS_TREND_ANALYZER",
    ):
        monkeypatch.delenv(env_name, raising=False)

    rows = {row["feature"]: row for row in config_store.get_llm_provider_settings()}

    assert rows["stock_pick"]["primary_provider"] == "anthropic"
    assert rows["stock_pick"]["shadow_providers"] == ["gemini"]
    assert rows["portfolio_signal"]["shadow_providers"] == ["gemini"]
    assert rows["eod_review"]["shadow_providers"] == []
    assert rows["trend_analyzer"]["shadow_providers"] == []


def test_get_llm_provider_settings_reads_env_overrides(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LLM_PROVIDER_STOCK_PICK", "openai")
    monkeypatch.setenv("LLM_SHADOW_PROVIDERS_STOCK_PICK", "anthropic,gemini")

    rows = {row["feature"]: row for row in config_store.get_llm_provider_settings()}

    assert rows["stock_pick"]["primary_provider"] == "openai"
    assert rows["stock_pick"]["shadow_providers"] == ["anthropic", "gemini"]


def test_env_updates_for_llm_provider_builds_correct_env_names() -> None:
    updates = config_store.env_updates_for_llm_provider(
        "eod_review", primary_provider="gemini", shadow_providers=["openai"]
    )
    assert updates == {"LLM_PROVIDER_EOD_REVIEW": "gemini", "LLM_SHADOW_PROVIDERS_EOD_REVIEW": "openai"}


def test_env_updates_for_llm_provider_omits_none_fields() -> None:
    updates = config_store.env_updates_for_llm_provider("stock_pick", primary_provider="openai", shadow_providers=None)
    assert updates == {"LLM_PROVIDER_STOCK_PICK": "openai"}


def test_env_updates_for_llm_provider_rejects_unknown_feature() -> None:
    with pytest.raises(ValueError, match="未知の機能"):
        config_store.env_updates_for_llm_provider("unknown", primary_provider="openai", shadow_providers=None)


def test_get_llm_provider_options_includes_default_model_and_presets(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ANTHROPIC_MODEL", raising=False)
    monkeypatch.setenv("OPENAI_MODEL", "gpt-5.1-mini")

    options = {o["value"]: o for o in config_store.get_llm_provider_options()}

    assert options["anthropic"]["default_model"] == "claude-sonnet-5"  # config.py のフィールド default
    assert options["openai"]["default_model"] == "gpt-5.1-mini"  # .env 上書きを反映
    assert "claude-opus-5" in cast("list[str]", options["anthropic"]["model_presets"])


def test_get_llm_provider_settings_models_fall_back_to_provider_default(monkeypatch: pytest.MonkeyPatch) -> None:
    for env_name in (
        "LLM_MODEL_STOCK_PICK_ANTHROPIC",
        "LLM_MODEL_STOCK_PICK_OPENAI",
        "LLM_MODEL_STOCK_PICK_GEMINI",
        "ANTHROPIC_MODEL",
    ):
        monkeypatch.delenv(env_name, raising=False)

    rows = {row["feature"]: row for row in config_store.get_llm_provider_settings()}

    assert _models(rows["stock_pick"])["anthropic"] == "claude-sonnet-5"


def test_get_llm_provider_settings_models_reflect_feature_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ANTHROPIC_MODEL", "claude-sonnet-5")
    monkeypatch.setenv("LLM_MODEL_STOCK_PICK_ANTHROPIC", "claude-opus-5")

    rows = {row["feature"]: row for row in config_store.get_llm_provider_settings()}

    assert _models(rows["stock_pick"])["anthropic"] == "claude-opus-5"
    # 他機能は上書きされていないのでプロバイダ既定値のまま。
    assert _models(rows["portfolio_signal"])["anthropic"] == "claude-sonnet-5"


def test_env_updates_for_llm_provider_includes_model_overrides() -> None:
    updates = config_store.env_updates_for_llm_provider(
        "stock_pick",
        primary_provider=None,
        shadow_providers=None,
        models={"anthropic": "claude-opus-5", "gemini": ""},
    )
    assert updates == {
        "LLM_MODEL_STOCK_PICK_ANTHROPIC": "claude-opus-5",
        "LLM_MODEL_STOCK_PICK_GEMINI": "",
    }


def test_env_updates_for_llm_provider_rejects_unknown_provider_in_models() -> None:
    with pytest.raises(ValueError, match="未知のプロバイダ"):
        config_store.env_updates_for_llm_provider(
            "stock_pick", primary_provider=None, shadow_providers=None, models={"bogus": "x"}
        )
