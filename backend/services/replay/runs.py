"""過去日リプレイ実行の管理（作成・起動・停止・生存判定、🆕 P37）.

リプレイは全期間で数十分〜数時間かかるため、backend（uvicorn）や celery worker（Windows は
`--pool=solo` の 1 本だけで、占有すると 07:30 のピック生成や保有監視が止まる）の中では動かさず、
**独立した子プロセス**（`python -m backend.services.replay --run-id ...`）として起動する。
進捗と状態は `replay_runs` に書かれるので、backend 再起動をまたいでも追跡・再開できる。

生存判定はハートビート（`heartbeat_at`）の鮮度で行う。Windows では `os.kill(pid, 0)` が
プロセス存在確認ではなく CTRL_C_EVENT 送信になるため、PID による判定は使わない。
"""

from __future__ import annotations

import datetime
import subprocess  # nosec B404 — 固定引数でリプレイ子プロセスを起動するためだけに使う
import sys
import uuid
from pathlib import Path
from typing import Final

from backend.services.db import replay_db
from backend.services.jst_time import JST
from backend.services.replay.engine import ReplayConfig, default_log_dir

_PROJECT_ROOT: Final[Path] = Path(__file__).resolve().parents[3]
# ハートビートがこれより古い running は、プロセスが落ちたとみなして再開を許可する
# （1 日分の処理は数秒、再学習 1 回でも数分。起動直後の日足取得も 50 日ごとに更新する）。
STALE_AFTER: Final[datetime.timedelta] = datetime.timedelta(minutes=15)
# 既定の期間: J-Quants の日足は約 5 年前まで取れるので、最初の 1 年を特徴量・ML の助走に使い
# 残り約 4 年をリプレイする。
_DEFAULT_REPLAY_YEARS: Final[int] = 4
ACTIVE_STATUSES: Final[frozenset[str]] = frozenset({"pending", "running", "stopping"})


def default_dates(today: datetime.date) -> tuple[str, str]:
    end = today - datetime.timedelta(days=1)
    start = end.replace(year=end.year - _DEFAULT_REPLAY_YEARS)
    return start.isoformat(), end.isoformat()


def is_alive(run: dict[str, object], *, now: datetime.datetime | None = None) -> bool:
    """実行中（またはこれから始まる）と判断できるか。ハートビートが古ければ死んでいるとみなす."""
    if run.get("status") not in ACTIVE_STATUSES:
        return False
    heartbeat = run.get("heartbeat_at") or run.get("updated_at")
    if not isinstance(heartbeat, str):
        return False
    current = now or datetime.datetime.now(JST)
    return current - datetime.datetime.fromisoformat(heartbeat) < STALE_AFTER


async def find_alive_run() -> dict[str, object] | None:
    for run in await replay_db.list_runs(limit=50):
        if is_alive(run):
            return run
    return None


def spawn(run_id: str) -> int:
    """リプレイ子プロセスを切り離して起動し、PID を返す（引数は検証済み UUID のみ）."""
    str(uuid.UUID(run_id))  # 念のため形式を再検証（シェルは使わないが引数へ任意文字列を渡さない）
    log_dir = default_log_dir()
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = (log_dir / f"{run_id}.log").open("ab")
    kwargs: dict[str, object] = {"cwd": str(_PROJECT_ROOT), "stdout": log_file, "stderr": subprocess.STDOUT}
    if sys.platform == "win32":
        kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS
    else:
        kwargs["start_new_session"] = True
    proc = subprocess.Popen(  # nosec B603 — 実行ファイルは現インタプリタ、引数は固定値と検証済み UUID のみ
        [sys.executable, "-m", "backend.services.replay", "--run-id", run_id], **kwargs  # type: ignore[call-overload]
    )
    return int(proc.pid)


async def create_and_start(start_date: str, end_date: str, config: ReplayConfig | None = None) -> str:
    run_id = str(uuid.uuid4())
    await replay_db.create_run(
        run_id, start_date=start_date, end_date=end_date, config=(config or ReplayConfig()).to_dict()
    )
    await replay_db.update_run(run_id, heartbeat_at=datetime.datetime.now(JST).isoformat(timespec="seconds"))
    pid = spawn(run_id)
    await replay_db.update_run(run_id, pid=pid)
    return run_id


async def resume(run_id: str) -> None:
    await replay_db.update_run(
        run_id, status="pending", error=None, heartbeat_at=datetime.datetime.now(JST).isoformat(timespec="seconds")
    )
    pid = spawn(run_id)
    await replay_db.update_run(run_id, pid=pid)
