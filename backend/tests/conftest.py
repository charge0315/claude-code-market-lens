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
from dataclasses import dataclass  # noqa: E402
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


@pytest.fixture(autouse=True)
def _isolated_calibrator_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """較正器（joblib）の保存先を毎テスト一時ディレクトリへ差し替える.

    `services/registry/calibration` はモジュールレベルの `_CALIBRATOR_DIR`（実リポジトリの
    `data/calibrators/`）へ無条件に書き込むため、これを autouse で隔離しないと、ある
    テストが学習した較正器を別テストが誤って読み込んでしまう（DB の per-file 隔離と同じ理由）。
    """
    from backend.services.registry import calibration

    monkeypatch.setattr(calibration, "_CALIBRATOR_DIR", tmp_path / "calibrators")


@pytest.fixture(autouse=True)
def _isolated_per_ticker_model_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """銘柄別モデル（P9）の既定保存先を毎テスト一時ディレクトリへ差し替える.

    `per_ticker_training_service._get_predictor` は `model_dir` を明示指定せずに
    predictor を生成するため、モジュールレベルの `_DEFAULT_MODEL_DIR`（実リポジトリの
    `data/models/`）へ無条件に書き込む。`_isolated_calibrator_dir` と同じ理由で隔離する。
    """
    from backend.services.learning import per_ticker_predictor
    from backend.services.learning.dl import base as dl_base

    monkeypatch.setattr(per_ticker_predictor, "_DEFAULT_MODEL_DIR", tmp_path / "models")
    monkeypatch.setattr(dl_base, "_DEFAULT_MODEL_DIR", tmp_path / "models")


@pytest.fixture(autouse=True)
def _use_thread_pool_for_training_batch(monkeypatch: pytest.MonkeyPatch) -> None:
    """🆕 日次学習バッチの並列化（`ProcessPoolExecutor`）をテストでは無効化する.

    `ProcessPoolExecutor` は `spawn` で子プロセスを新しい Python インタプリタとして
    起動するため、`_isolated_per_ticker_model_dir` 等の monkeypatch によるモデル保存先の
    隔離は子プロセスへ一切引き継がれない（引き継がれると、テストが本物の `data/models/`
    へ書き込んでしまう）。`_create_worker_pool` が `None` を返すと
    `loop.run_in_executor(None, ...)` は同一プロセス内のデフォルトスレッドプールを使うため、
    monkeypatch が正しく効いたまま「ウィンドウ単位の並列処理」というオーケストレーション
    ロジック自体はテストできる（実プロセス分離そのものは対象外、手動検証に委ねる）。
    """
    from backend.services.learning import per_ticker_training_service

    monkeypatch.setattr(per_ticker_training_service, "_create_worker_pool", lambda _max_workers: None)


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
    """`init_db()` 済みの隔離 DB を渡す（テーブルは作らない）."""
    from backend.services.db.database import dispose_db, init_db

    await init_db()
    yield isolated_db
    await dispose_db()


@pytest_asyncio.fixture
async def migrated_db(isolated_db: Path) -> AsyncIterator[Path]:
    """Alembic を head まで適用した隔離 DB を渡す（実テーブルが必要なテスト用）."""
    from alembic import command
    from alembic.config import Config

    from backend.services.db.database import dispose_db

    repo_root = Path(__file__).resolve().parents[2]
    cfg = Config(str(repo_root / "backend" / "alembic.ini"))
    cfg.set_main_option("script_location", str(repo_root / "backend" / "alembic"))
    cfg.set_main_option("sqlalchemy.url", f"sqlite:///{isolated_db.as_posix()}")
    command.upgrade(cfg, "head")

    yield isolated_db
    await dispose_db()


@dataclass(frozen=True)
class VaultDirs:
    """テスト用の一時 Vault ディレクトリ一式."""

    root: Path
    tickers: Path
    daily: Path


@pytest.fixture
def vault_dirs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> VaultDirs:
    """`settings.vault_root` を一時ディレクトリへ差し替え、`Tickers/` `Daily/` を用意する.

    `resolved_brand_notes_dir` / `resolved_daily_notes_dir` は vault_root からの導出プロパティ
    なので、`brand_notes_dir` / `daily_notes_dir` は空のままにして vault_root だけを差し替える。
    """
    from backend import config
    from backend.services.vault import brand_notes_service, daily_note_service, news_digest_service
    from backend.services.vault_report import vault_writer

    root = tmp_path / "vault"
    tickers = root / "Tickers"
    daily = root / "Daily"
    tickers.mkdir(parents=True)
    daily.mkdir(parents=True)

    new_settings = config.settings.model_copy(
        update={"vault_root": str(root), "brand_notes_dir": "", "daily_notes_dir": ""}
    )
    for mod in (config, brand_notes_service, news_digest_service, daily_note_service, vault_writer):
        monkeypatch.setattr(mod, "settings", new_settings)
    brand_notes_service.clear_cache()
    news_digest_service.clear_cache()
    return VaultDirs(root=root, tickers=tickers, daily=daily)
