"""Alembic 実行環境.

`backend/config.py` の `settings.database_url` を唯一の情報源とする。async ドライバ
（aiosqlite / asyncpg）を Alembic 用に同期ドライバへ読み替えてから接続する。
"""

from __future__ import annotations

from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from backend.config import settings

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# 宣言的モデルはまだ持たない（マイグレーションが唯一の真実）。autogenerate は使わない。
target_metadata = None


def _sync_url(url: str) -> str:
    """async ドライバの URL を Alembic 用の同期ドライバへ読み替える."""
    return url.replace("+aiosqlite", "").replace("+asyncpg", "+psycopg")


def _resolve_url() -> str:
    """接続先 URL を決める.

    alembic.ini / CLI（`-x` や `set_main_option`）で `sqlalchemy.url` が明示されて
    いればそれを優先する（テストや一時 DB の差し替えに使う）。無ければ
    `backend/config.py` の `settings.database_url` を唯一の情報源とする。
    """
    explicit = config.get_main_option("sqlalchemy.url")
    return _sync_url(explicit) if explicit else _sync_url(settings.database_url)


def run_migrations_offline() -> None:
    """URL だけで SQL を生成する offline モード."""
    context.configure(
        url=_resolve_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        render_as_batch=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """実接続して適用する online モード."""
    section = config.get_section(config.config_ini_section, {})
    section["sqlalchemy.url"] = _resolve_url()
    connectable = engine_from_config(section, prefix="sqlalchemy.", poolclass=pool.NullPool)

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            render_as_batch=True,  # SQLite の ALTER 制約を回避
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
