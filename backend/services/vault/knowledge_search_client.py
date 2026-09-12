"""既存の外部ナレッジベース・ベクトル検索サービス（kb_creator、Qdrant バックエンド）への
読み取り専用クライアント.

ユーザーの Obsidian Vault（`VAULT_ROOT` 配下、`10_Stock/Tickers/` `10_Stock/Daily/` 含む）を
既に別プロセス（`settings.kb_search_url`）がインデックス済みで、`POST /search` で意味検索
できる。本モジュールは**関連ノートの発見**だけに使う — 応答の `text`（マッチしたチャンクの
本文）はこのクライアント関数の戻り値（`KnowledgeSearchHit`）に一切含めない。

**プロンプトインジェクション防御**（CLAUDE.md「外部由来テキストは frontmatter のみ」）を
呼び出し側が意識せず守れるよう、境界をこの薄いクライアント自身に集約する: 呼び出し側
（`services/picks/prompt.py` 等）は `note_path` から日付/コードを取り出し、
`brand_notes_service.get_brand_note` / `daily_note_service.read_daily_frontmatter` の
frontmatter 専用関数で改めて取得したものだけをプロンプトへ載せること。

`settings.kb_search_url` が空（既定）、または接続失敗・タイムアウトの場合は常に空リストへ
フォールバックする（ベストエフォートの補助情報であり、意思決定をブロックしない）。
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass

import httpx

from backend.config import settings

logger = logging.getLogger(__name__)

# 1銘柄あたりの取得件数。多すぎると無関係なノートまで frontmatter 再取得の対象になるため、
# 上位数件に絞る（既存の brand_frontmatter 1件 + α程度の軽い補助情報という位置づけ）。
_TOP_K = 3

_DAILY_NOTE_PATH_RE = re.compile(r"Daily/(\d{4}-\d{2}-\d{2})\.md$")


@dataclass(frozen=True)
class KnowledgeSearchHit:
    """検索1件分の「発見」情報のみ（本文・見出しパスは含まない — 本文を保持しない設計を
    型でも徹底するため、`text`/`heading_path` は最初からフィールドに持たない）."""

    note_path: str
    doc_type: str
    score: float


async def search_ticker_notes(query: str, *, code: str) -> list[KnowledgeSearchHit]:
    """指定銘柄コードにスコープした関連ノートを検索する（未設定・失敗時は空リスト）.

    `code` で `SearchRequest.code` フィルタを掛け、当該銘柄自身のノート（`Tickers/<code>.md`
    本体、および同コードでタグ付けされた `Daily/` ノート等）に検索範囲を限定する。
    """
    if not settings.kb_search_url:
        return []

    try:
        async with httpx.AsyncClient(timeout=settings.kb_search_timeout_seconds) as client:
            res = await client.post(
                f"{settings.kb_search_url.rstrip('/')}/search",
                json={"query": query, "top_k": _TOP_K, "code": code},
            )
            res.raise_for_status()
            body = res.json()
    except (httpx.HTTPError, ValueError):
        logger.warning("ナレッジベース検索に失敗しました（銘柄=%s）", code, exc_info=True)
        return []

    results = body.get("results") if isinstance(body, dict) else None
    if not isinstance(results, list):
        return []

    hits: list[KnowledgeSearchHit] = []
    for item in results:
        if not isinstance(item, dict):
            continue
        note_path = item.get("note_path")
        doc_type = item.get("doc_type")
        score = item.get("score")
        if (
            isinstance(note_path, str)
            and isinstance(doc_type, str)
            and isinstance(score, int | float)
            and not isinstance(score, bool)
        ):
            hits.append(KnowledgeSearchHit(note_path=note_path, doc_type=doc_type, score=float(score)))
    return hits


def extract_related_daily_dates(hits: list[KnowledgeSearchHit]) -> list[str]:
    """検索ヒットのうち `Daily/YYYY-MM-DD.md` 由来のものから日付だけを重複無く抽出する.

    抽出した日付は呼び出し側が `daily_note_service.read_daily_frontmatter(date)` で
    frontmatter を再取得するためのキーとして使う（本文には触れない）。
    """
    dates: list[str] = []
    for hit in hits:
        match = _DAILY_NOTE_PATH_RE.search(hit.note_path)
        if match and match.group(1) not in dates:
            dates.append(match.group(1))
    return dates
