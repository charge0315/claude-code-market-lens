"""API 共通レスポンスエンベロープ.

`~/.claude/rules/common/patterns.md` の「API Response Format」に従い、全 API 応答を
`{ success, data, error, meta? }` の一貫した封筒で返す。ジェネリックで型付けし、
`data` の型をルーターごとに固定する。
"""

from __future__ import annotations

from typing import Generic, TypeVar

from pydantic import BaseModel, ConfigDict

T = TypeVar("T")


class PageMeta(BaseModel):
    """ページネーション応答のメタ情報."""

    model_config = ConfigDict(frozen=True)

    total: int
    page: int
    limit: int


class ApiResponse(BaseModel, Generic[T]):
    """全 API 応答の共通封筒.

    `success=True` のとき `data` が入り `error` は None、失敗時は逆。
    ルーターは基本的に成功応答だけを組み立て、失敗は例外ハンドラが封筒へ整形する。
    """

    model_config = ConfigDict(frozen=True)

    success: bool
    data: T | None = None
    error: str | None = None
    meta: PageMeta | None = None

    @classmethod
    def ok(cls, data: T, meta: PageMeta | None = None) -> ApiResponse[T]:
        """成功応答を組み立てる."""
        return cls(success=True, data=data, error=None, meta=meta)

    @classmethod
    def fail(cls, error: str) -> ApiResponse[T]:
        """失敗応答を組み立てる."""
        return cls(success=False, data=None, error=error, meta=None)
