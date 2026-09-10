"""DB 接続とスキーマ初期化.

SQLAlchemy の async エンジンを使い、既定は SQLite（aiosqlite）。`database_url` を
PostgreSQL の DSN に差し替えるだけで移行できる設計にする（`plans/02` の方針）。

- `get_db()`: リクエストスコープの `AsyncConnection` を渡す非同期コンテキストマネージャ。
- `init_db()`: アプリ起動時に呼ぶ。SQLite ではファイルの親ディレクトリを作成し、
  外部キー制約を有効化する。テーブル定義そのものは Alembic マイグレーションが所有する。
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine, create_async_engine

from backend.config import settings

_engine: AsyncEngine | None = None


def _sqlite_path_from_url(url: str) -> Path | None:
    """`sqlite+aiosqlite:///./data/x.db` 形式からファイルパスを取り出す（SQLite 以外は None）."""
    marker = ":///"
    if "sqlite" not in url or marker not in url:
        return None
    return Path(url.split(marker, 1)[1])


def get_engine() -> AsyncEngine:
    """プロセスで 1 つの AsyncEngine を遅延生成して返す."""
    global _engine
    if _engine is None:
        _engine = create_async_engine(settings.database_url, future=True)

        # SQLite は既定で外部キー制約を無効にするため、接続ごとに PRAGMA で有効化する。
        if settings.database_url.startswith("sqlite"):

            @event.listens_for(_engine.sync_engine, "connect")
            def _fk_on(dbapi_conn: object, _rec: object) -> None:
                cur = dbapi_conn.cursor()  # type: ignore[attr-defined]
                cur.execute("PRAGMA foreign_keys=ON")
                cur.close()

    return _engine


async def init_db() -> None:
    """起動時のスキーマ前提を整える（SQLite ファイルの親ディレクトリ作成と疎通確認）."""
    path = _sqlite_path_from_url(settings.database_url)
    if path is not None:
        path.parent.mkdir(parents=True, exist_ok=True)

    async with get_engine().begin() as conn:
        await conn.execute(text("SELECT 1"))


async def dispose_db() -> None:
    """シャットダウン時にコネクションプールを解放する."""
    global _engine
    if _engine is not None:
        await _engine.dispose()
        _engine = None


@asynccontextmanager
async def get_db() -> AsyncIterator[AsyncConnection]:
    """トランザクション境界付きの AsyncConnection を渡す.

    正常終了で commit、例外で rollback。ルーターは `async with get_db() as db:` で使う。
    """
    async with get_engine().begin() as conn:
        yield conn
