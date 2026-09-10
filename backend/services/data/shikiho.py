"""四季報情報のデータソース（当面スタブ）.

`新規プロジェクト構築プロンプト.md` §4 / §11-1 の確定事項に基づき、四季報は
データソースが確定するまでスタブとする（feature flag ``SHIKIHO_ENABLED``、既定 ``false``）。

- ``SHIKIHO_ENABLED=false``（既定）: ``get_shikiho`` は常に ``None`` を返す。fundamental の
  補完は Vault ``Tickers/*.md`` の frontmatter 財務指標 + J-Quants が担う
  （`services/vault/brand_notes_service.py`）。
- ``SHIKIHO_ENABLED=true``: データソース実装後にここへ差し込む。注入するのは frontmatter /
  構造化フィールドのみ（本文・記事テキストは注入しない）。

呼び出し側は「``None`` なら四季報なし」として扱えばよく、feature flag を意識しなくてよい。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from backend.config import settings

logger = logging.getLogger(__name__)

_warned = False


@dataclass(frozen=True)
class ShikihoRecord:
    """四季報から抽出する構造化フィールド（データソース確定後に拡張する）.

    現時点ではプレースホルダ。本文・記事の生テキストはこの型に含めない
    （プロンプトインジェクション対策。CLAUDE.md「外部由来テキストは frontmatter のみ」）。
    """

    code: str
    # 例: 会社比予想（連/単）、前号比、来期予想の方向などの構造化値をここへ足していく。


async def get_shikiho(code: str) -> ShikihoRecord | None:
    """指定コードの四季報構造化情報を返す（スタブ期間中は常に ``None``）."""
    global _warned
    if not settings.shikiho_enabled:
        return None
    if not _warned:
        logger.warning(
            "SHIKIHO_ENABLED=true ですが四季報データソースは未実装です（%s ほか全銘柄で None を返します）",
            code,
        )
        _warned = True
    return None
