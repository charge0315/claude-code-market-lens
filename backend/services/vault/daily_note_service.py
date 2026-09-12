"""マーケットデイリーノート（Obsidian Vault ``Daily/YYYY-MM-DD.md``）へのアクセス.

Market Lens `backend/services/daily_note_service.py` から移植。変更点（🔧）:
- **当面は読み取り専用**。Market Lens は朝夕 2 フェーズで本文の managed region を書き換えるが、
  Alpha Forge から Vault へ書き込む場合は Market Lens と衝突しない Alpha Forge 専用マーカーに
  限定し、実行前にユーザー確認する（`plans/00_調査サマリ` §2.2、CLAUDE.md「Vault は read-only が原則」）。
  そのため書き込み関数は用意せず、P7（EOD レビュー → learned heuristics）で必要になった時点で
  専用マーカー付きで追加する。
- 読み取りは frontmatter のみ（本文の morning/evening/review ブロックは自己参照ループ防止で読まない）。
- 🔧 P9（ナレッジベース検索）で発見: `date: 2026-06-01` のようにクォート無しの日付は
  `yaml.safe_load` が `datetime.date` にパースするため、そのまま `json.dumps`（LLM プロンプト
  組み立て）へ渡すと `TypeError` になる。frontmatter を返す直前に日付/日時値を ISO 文字列へ
  正規化する（`_normalize_frontmatter_values`）。
"""

from __future__ import annotations

import re
from datetime import date
from pathlib import Path

import yaml

from backend.config import settings
from backend.services.jst_time import today_jst

_FRONTMATTER_RE = re.compile(r"^---[ \t]*\r?\n(.*?)\r?\n---[ \t]*\r?\n", re.DOTALL)


def _normalize_frontmatter_values(frontmatter: dict[str, object]) -> dict[str, object]:
    """`date`/`datetime` 値を ISO 文字列へ正規化する（`datetime` は `date` のサブクラスのため
    `isinstance(value, date)` で両方カバーする。JSON シリアライズ可能にするため）.
    """
    return {key: value.isoformat() if isinstance(value, date) else value for key, value in frontmatter.items()}


def daily_note_path(target: date | str | None = None) -> Path:
    """指定日（既定は JST 本日）の日次ノートのパスを返す（存在は保証しない）."""
    day = target.isoformat() if isinstance(target, date) else (target or today_jst())
    return settings.resolved_daily_notes_dir / f"{day}.md"


def daily_note_exists(target: date | str | None = None) -> bool:
    """指定日の日次ノートが存在するかを返す."""
    return daily_note_path(target).is_file()


def read_daily_frontmatter(target: date | str | None = None) -> dict[str, object] | None:
    """指定日の日次ノートの frontmatter を dict で返す（無い・不正なら ``None``、本文は読まない）."""
    path = daily_note_path(target)
    if not path.is_file():
        return None
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return None
    match = _FRONTMATTER_RE.match(text)
    if match is None:
        return None
    try:
        loaded = yaml.safe_load(match.group(1))
    except yaml.YAMLError:
        return None
    return _normalize_frontmatter_values(loaded) if isinstance(loaded, dict) else None
