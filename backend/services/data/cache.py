"""SQLite-backed TTL キャッシュ（株価データ・企業情報）.

Market Lens `backend/services/cache.py` から移植。変更点:
- キャッシュ DB のパスを `backend/data/stock_cache.db` → リポジトリルート `data/cache/stock_cache.db`
  に変更（`.gitignore` の `data/cache/` 配下でコミット対象外）。

`data_fetcher.py` の同期コードから使われるため aiosqlite ではなく標準 sqlite3 で実装する。
DataFrame は to_json/read_json、dict は json.dumps/loads でシリアライズする。DB は最初の
アクセス時に遅延初期化する。
"""

from __future__ import annotations

import json
import logging
import sqlite3
import threading
import time
from collections.abc import Mapping
from io import StringIO
from pathlib import Path

import pandas as pd

logger = logging.getLogger(__name__)

# リポジトリルート = backend/services/data/cache.py から 4 つ上。
_CACHE_DIR: Path = Path(__file__).resolve().parents[3] / "data" / "cache"
_CACHE_DB_PATH: Path = _CACHE_DIR / "stock_cache.db"

_DDL = """
CREATE TABLE IF NOT EXISTS stock_cache (
    cache_key  TEXT NOT NULL,
    value_text TEXT NOT NULL,
    value_type TEXT NOT NULL,
    cached_at  REAL NOT NULL,
    ttl        INTEGER NOT NULL,
    PRIMARY KEY (cache_key, value_type)
)
"""


class StockCache:
    """SQLite を使った TTL 付き株価データキャッシュ（接続は操作ごとに都度生成する）."""

    def __init__(self, db_path: Path = _CACHE_DB_PATH) -> None:
        self._db_path = db_path
        self._lock = threading.Lock()
        self._initialized = False

    def _ensure_init(self) -> None:
        """DB が未初期化であれば初期化する（ダブルチェックロッキング）."""
        if self._initialized:
            return
        with self._lock:
            if not self._initialized:
                self._init_db()
                self._initialized = True

    def _init_db(self) -> None:
        """キャッシュ DB とテーブルを作成する."""
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.execute(_DDL)
            conn.commit()
        logger.info("キャッシュ DB を初期化しました: %s", self._db_path)

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self._db_path))
        # 並列アクセス時の書き込み競合を避けるため WAL + busy_timeout。
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=10000")
        return conn

    def _is_valid(self, cached_at: float, ttl: int) -> bool:
        return (time.time() - cached_at) < ttl

    # --- DataFrame キャッシュ ---

    def get_dataframe(self, key: str) -> pd.DataFrame | None:
        """キャッシュされた DataFrame を取得する（TTL 切れ・未存在なら None）."""
        self._ensure_init()
        with self._lock, self._connect() as conn:
            row = conn.execute(
                "SELECT value_text, cached_at, ttl FROM stock_cache"
                " WHERE cache_key = ? AND value_type = 'dataframe'",
                (key,),
            ).fetchone()

        if row is None:
            return None
        value_text, cached_at, ttl = row
        if not self._is_valid(cached_at, ttl):
            logger.debug("キャッシュ期限切れ: %s", key)
            return None
        try:
            return pd.read_json(StringIO(value_text))
        except Exception:
            logger.exception("DataFrame のデシリアライズに失敗: %s", key)
            return None

    def set_dataframe(self, key: str, df: pd.DataFrame, ttl: int = 300) -> None:
        """DataFrame をキャッシュに保存する."""
        self._ensure_init()
        value_text = df.to_json(date_format="iso")
        with self._lock, self._connect() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO stock_cache"
                " (cache_key, value_text, value_type, cached_at, ttl)"
                " VALUES (?, ?, 'dataframe', ?, ?)",
                (key, value_text, time.time(), ttl),
            )
            conn.commit()
        logger.debug("DataFrame をキャッシュ保存: %s (ttl=%ds)", key, ttl)

    # --- dict / JSON キャッシュ ---

    def get_json(self, key: str) -> dict[str, object] | None:
        """キャッシュされた dict を取得する（TTL 切れ・未存在なら None）."""
        self._ensure_init()
        with self._lock, self._connect() as conn:
            row = conn.execute(
                "SELECT value_text, cached_at, ttl FROM stock_cache WHERE cache_key = ? AND value_type = 'json'",
                (key,),
            ).fetchone()

        if row is None:
            return None
        value_text, cached_at, ttl = row
        if not self._is_valid(cached_at, ttl):
            return None
        try:
            loaded = json.loads(value_text)
        except Exception:
            logger.exception("JSON のデシリアライズに失敗: %s", key)
            return None
        return loaded if isinstance(loaded, dict) else None

    def set_json(self, key: str, value: Mapping[str, object], ttl: int = 3600) -> None:
        """dict をキャッシュに保存する."""
        self._ensure_init()
        with self._lock, self._connect() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO stock_cache"
                " (cache_key, value_text, value_type, cached_at, ttl)"
                " VALUES (?, ?, 'json', ?, ?)",
                (key, json.dumps(value, ensure_ascii=False), time.time(), ttl),
            )
            conn.commit()

    # --- メンテナンス ---

    def clear_expired(self) -> int:
        """期限切れのエントリを削除し、削除件数を返す."""
        self._ensure_init()
        now = time.time()
        with self._lock, self._connect() as conn:
            cursor = conn.execute("DELETE FROM stock_cache WHERE (? - cached_at) >= ttl", (now,))
            conn.commit()
            return cursor.rowcount

    def vacuum(self) -> None:
        """DB ファイルを圧縮する（VACUUM）。DELETE だけではファイルサイズが縮まないため."""
        self._ensure_init()
        with self._lock, self._connect() as conn:
            conn.execute("VACUUM")
        logger.info("キャッシュ DB を VACUUM しました: %s", self._db_path)

    def clear_all(self) -> None:
        """全キャッシュエントリを削除する（主にテスト用）."""
        self._ensure_init()
        with self._lock, self._connect() as conn:
            conn.execute("DELETE FROM stock_cache")
            conn.commit()


# モジュールレベルのシングルトン（DB 作成は最初の操作まで遅延）。
stock_cache: StockCache = StockCache()
