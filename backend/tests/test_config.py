"""設定モジュールの検証."""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from backend.config import Settings, settings


def test_defaults_match_alpha_forge_ports() -> None:
    """既定ポートは Market Lens（8001 / 3000）と衝突しない 8002 / 3001."""
    assert settings.backend_port == 8002
    assert settings.frontend_port == 3001


def test_vault_dirs_are_derived_from_root_when_unset() -> None:
    """`BRAND_NOTES_DIR` / `DAILY_NOTES_DIR` 未指定なら VAULT_ROOT から導出する."""
    s = Settings(
        ML_SECRET_KEY="x" * 16,
        ML_PASSWORD_HASH="h",
        VAULT_ROOT=r"C:\vault",
    )
    assert s.resolved_brand_notes_dir == Path(r"C:\vault") / "Tickers"
    assert s.resolved_daily_notes_dir == Path(r"C:\vault") / "Daily"


def test_explicit_vault_dir_overrides_derivation() -> None:
    """明示指定した Vault サブディレクトリは導出値より優先される."""
    s = Settings(
        ML_SECRET_KEY="x" * 16,
        ML_PASSWORD_HASH="h",
        VAULT_ROOT=r"C:\vault",
        BRAND_NOTES_DIR=r"D:\notes\tickers",
    )
    assert s.resolved_brand_notes_dir == Path(r"D:\notes\tickers")


def test_short_secret_key_is_rejected_at_construction() -> None:
    """16 文字未満の署名鍵は起動時に弾く（fail-fast）."""
    with pytest.raises(ValidationError):
        Settings(ML_SECRET_KEY="short", ML_PASSWORD_HASH="h")


def test_model_auto_promote_defaults_off() -> None:
    """自動昇格は既定 OFF（昇格は API 承認でのみ）."""
    assert settings.model_auto_promote is False


def test_paper_min_days_default_is_twenty() -> None:
    """champion 昇格ゲートの最小ペーパー成績日数は 20 営業日（P0 確認済み）."""
    assert settings.paper_min_days == 20


def test_cors_origins_accepts_csv_string() -> None:
    """カンマ区切り文字列の CORS_ORIGINS を list へ変換する."""
    s = Settings(
        ML_SECRET_KEY="x" * 16,
        ML_PASSWORD_HASH="h",
        ML_CORS_ORIGINS="http://a.example, http://b.example",
    )
    assert s.cors_origins == ["http://a.example", "http://b.example"]
