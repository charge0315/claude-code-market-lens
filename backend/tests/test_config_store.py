"""`services/config_store.py`（外部 API キーのマスク表示・.env 永続化）の検証."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from backend.services import config_store


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
