"""日次ノートの読み取り専用アクセスの検証."""

from __future__ import annotations

from backend.services.vault.daily_note_service import (
    daily_note_exists,
    daily_note_path,
    read_daily_frontmatter,
)
from backend.tests.conftest import VaultDirs


def test_path_and_existence(vault_dirs: VaultDirs) -> None:
    assert daily_note_path("2026-09-10") == vault_dirs.daily / "2026-09-10.md"
    assert daily_note_exists("2026-09-10") is False
    (vault_dirs.daily / "2026-09-10.md").write_text(
        "---\ndate: 2026-09-10\ncategory: 市況\ntype: daily-note\n---\n\n# 本文は読まない\n",
        encoding="utf-8",
    )
    assert daily_note_exists("2026-09-10") is True


def test_read_frontmatter_only(vault_dirs: VaultDirs) -> None:
    (vault_dirs.daily / "2026-09-10.md").write_text(
        "---\ndate: 2026-09-10\ncategory: 市況\nfact_checked: true\ntype: daily-note\n---\n\n本文 SECRET\n",
        encoding="utf-8",
    )
    fm = read_daily_frontmatter("2026-09-10")
    assert fm is not None
    # 🔧 未クオートの YAML 日付は yaml.safe_load が datetime.date にパースするため、
    # json.dumps（LLM プロンプト組み立て）で TypeError になっていた。ISO 文字列へ正規化する。
    assert fm["date"] == "2026-09-10"
    assert fm["category"] == "市況"
    assert fm["fact_checked"] is True
    assert "本文" not in repr(fm)
    assert "SECRET" not in repr(fm)


def test_missing_note_returns_none(vault_dirs: VaultDirs) -> None:
    assert read_daily_frontmatter("2020-01-01") is None


def test_frontmatter_is_json_serializable(vault_dirs: VaultDirs) -> None:
    """フロントマターの戻り値は常に JSON エンコード可能であること（LLM プロンプト組み立てで使うため）."""
    import json

    (vault_dirs.daily / "2026-09-10.md").write_text(
        "---\ndate: 2026-09-10\ncategory: 市況\n---\n\n本文\n", encoding="utf-8"
    )
    fm = read_daily_frontmatter("2026-09-10")
    assert fm is not None
    json.dumps(fm, ensure_ascii=False)  # 例外が出ないことを確認
