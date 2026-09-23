"""過去日リプレイの子プロセス入口（🆕 P37）.

`python -m backend.services.replay --run-id <uuid>`。API（`routers/replay.py`）が `runs.spawn` で
起動する。手動で直接叩いてもよい（`replay_runs` に行が存在する run_id に限る）。
"""

from __future__ import annotations

import argparse
import asyncio
import datetime
import logging
import sys
import uuid
from pathlib import Path

from dotenv import load_dotenv

# 子プロセス単独起動では backend/main.py の load_dotenv() が走らないため、ここで明示的に読む
# （celery_app.py と同じ理由）。設定（J-Quants キー・DB URL）を読む import より前に行う。
load_dotenv(Path(__file__).resolve().parents[3] / ".env")

from backend.services.db import replay_db  # noqa: E402 — load_dotenv の後に import する必要がある
from backend.services.db.database import dispose_db  # noqa: E402
from backend.services.jst_time import JST  # noqa: E402
from backend.services.replay.engine import run_replay  # noqa: E402
from backend.services.replay.price_store import DEFAULT_CACHE_DIR, ensure_bar_cache, load_price_store  # noqa: E402

logger = logging.getLogger("backend.services.replay")

# リプレイ開始日より前に読み込む暦日数（テクニカル採点の 1 年 + 特徴量の助走）。
_WARMUP_CALENDAR_DAYS = 400


async def _heartbeat(run_id: str, _date: str) -> None:
    await replay_db.update_run(run_id, heartbeat_at=datetime.datetime.now(JST).isoformat(timespec="seconds"))


async def main(run_id: str) -> int:
    run = await replay_db.get_run(run_id)
    if run is None:
        logger.error("リプレイ %s が見つかりません", run_id)
        return 2
    start = str(run["start_date"])
    end = str(run["end_date"])
    cache_start = (datetime.date.fromisoformat(start) - datetime.timedelta(days=_WARMUP_CALENDAR_DAYS)).isoformat()
    if run.get("status") == "stopping":
        await replay_db.update_run(run_id, status="stopped")
        return 0
    try:
        await replay_db.update_run(run_id, status="running", error=None)
        logger.info("リプレイ %s: 日足キャッシュを準備（%s〜%s）", run_id, cache_start, end)
        await ensure_bar_cache(
            cache_start, end, cache_dir=DEFAULT_CACHE_DIR, on_progress=lambda d: _heartbeat(run_id, d)
        )
        store = await asyncio.to_thread(load_price_store, DEFAULT_CACHE_DIR, cache_start, end)
        status = await run_replay(run_id, store)
        logger.info("リプレイ %s: 終了（%s）", run_id, status)
        return 0
    except Exception as exc:  # noqa: BLE001 — 子プロセスの最上位。失敗を台帳に残して非 0 で終える
        logger.exception("リプレイ %s が失敗しました", run_id)
        await replay_db.update_run(run_id, status="failed", error=f"{type(exc).__name__}: {exc}")
        return 1
    finally:
        await dispose_db()


def _parse_args(argv: list[str]) -> str:
    parser = argparse.ArgumentParser(description="過去日リプレイ学習を実行する")
    parser.add_argument("--run-id", required=True)
    return str(uuid.UUID(parser.parse_args(argv).run_id))


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    sys.exit(asyncio.run(main(_parse_args(sys.argv[1:]))))
