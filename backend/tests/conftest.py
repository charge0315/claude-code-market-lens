"""テスト共通のフィクスチャ.

- 必須 env（`ML_SECRET_KEY` / `ML_PASSWORD_HASH`）をテスト用ダミーで満たす。
  `backend.config` は import 時に `Settings()` を評価するため、`conftest` の
  import より前（＝収集の最初期）に環境変数を差し込む必要がある。ここでは
  モジュールトップで `os.environ` を設定する。
- DB は per-file で一時ファイルへ隔離する（グローバル分離は持たない方針）。
"""

from __future__ import annotations

import os

os.environ.setdefault("ML_SECRET_KEY", "test-secret-key-32chars-minimum!!")
os.environ.setdefault("ML_PASSWORD_HASH", "$2b$12$0123456789012345678901uAbCdEfGhIjKlMnOpQrStUvWxYz012")

from collections.abc import AsyncIterator, Iterator  # noqa: E402
from pathlib import Path  # noqa: E402

import pytest  # noqa: E402
import pytest_asyncio  # noqa: E402


@pytest.fixture(autouse=True)
def _reset_shared_clients() -> Iterator[None]:
    """テストごとに event loop 束縛のプロセス共有クライアントを捨てる.

    pytest-asyncio は関数ごとに新しい event loop を張るため、`redis.asyncio` の
    クライアントや SQLAlchemy async エンジンをモジュールレベルでキャッシュしたまま
    次のテストへ持ち越すと「Event loop is closed」で落ちる。各テストの前後で
    キャッシュを None に戻し、次回アクセス時に現在のループで作り直させる。
    """
    from backend.services import task_registry
    from backend.services.db import database

    task_registry._client = None
    database._engine = None
    yield
    task_registry._client = None
    database._engine = None


@pytest.fixture
def isolated_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    """このテスト関数専用の SQLite ファイルへ `settings.database_url` を差し替える."""
    from backend import config
    from backend.services.db import database

    db_path = tmp_path / "alpha_forge_test.db"
    new_settings = config.settings.model_copy(update={"database_url": f"sqlite+aiosqlite:///{db_path.as_posix()}"})
    monkeypatch.setattr(config, "settings", new_settings)
    monkeypatch.setattr(database, "settings", new_settings)
    monkeypatch.setattr(database, "_engine", None)
    yield db_path
    monkeypatch.setattr(database, "_engine", None)


@pytest_asyncio.fixture
async def initialized_db(isolated_db: Path) -> AsyncIterator[Path]:
    """`init_db()` 済みの隔離 DB を渡す."""
    from backend.services.db.database import dispose_db, init_db

    await init_db()
    yield isolated_db
    await dispose_db()
