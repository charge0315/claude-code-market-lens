"""日次noteドラフト（🆕）のスキーマ.

本日のAIピック分析結果をもとに、有料note記事として配信するための下書きを自動生成し、
人間が確認・編集・承認してから手動で note.com へ投稿する（半自動、CLAUDE.md の
「AIは提案するだけ、実行は人間」という承認制パターンを踏襲）。note.com にはサードパーティ
向けの公式投稿APIが無いため、投稿そのものは常に人間が行う — このアプリは下書き生成と
状態追跡のみを担う。
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict

NoteStatus = Literal["draft", "approved", "rejected", "published"]


class DailyNote(BaseModel):
    """1 日 1 件の note ドラフト（`daily_notes` テーブルに対応、`note_date` で一意）."""

    model_config = ConfigDict(frozen=True)

    note_id: str
    note_date: str  # JST YYYY-MM-DD
    title: str
    body_markdown: str
    status: NoteStatus
    source_pick_ids: list[str]
    model_version: str
    has_price_mention_warning: bool
    generated_at: str
    approved_at: str | None = None
    published_at: str | None = None
    published_url: str | None = None


class NoteUpdateRequest(BaseModel):
    """`PATCH /api/notes/{note_id}` のリクエストボディ（本文の手直し）."""

    model_config = ConfigDict(frozen=True)

    title: str
    body_markdown: str


class NoteMarkPublishedRequest(BaseModel):
    """`POST /api/notes/{note_id}/mark-published` のリクエストボディ."""

    model_config = ConfigDict(frozen=True)

    published_url: str


class NoteExportResult(BaseModel):
    """`POST /api/notes/{note_id}/export` の応答（保存先ディレクトリのみ）."""

    model_config = ConfigDict(frozen=True)

    note_dir: str
