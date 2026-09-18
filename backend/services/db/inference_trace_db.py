"""`inference_traces` の読み書き（SQLAlchemy async）.

`plans/03_システム設計` §1.6（N4/VZ-6）。1 銘柄の推論オーケストレータ実行（`run_id`）ごとに
ステージ遷移を逐次 INSERT する（リプレイ・SSE 配信の単一の真実源。UPDATE はしない）。
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime

from sqlalchemy import text

from backend.services.db.database import get_db
from backend.services.jst_time import JST


def _parse_payload(row: dict[str, object]) -> dict[str, object]:
    row["payload"] = json.loads(str(row.get("payload") or "{}"))
    return row


async def insert_trace_event(
    *,
    run_id: str,
    symbol: str,
    horizon_type: str,
    status: str,
    stage: str,
    stage_status: str,
    stage_seq: int,
    payload: dict[str, object],
    started_at: str,
    finished_at: str | None = None,
    pick_id: str | None = None,
    event_at: str | None = None,
) -> None:
    """1 ステージの状態遷移を1行追加する.

    `status`/`finished_at`/`pick_id` は run 全体の時点スナップショット（呼び出し側がステージ
    ごとに最新値を渡す）。`inference_traces` は追記専用で UPDATE しないため、run の最終状態は
    「その run の最大 `stage_seq` を持つ行」から読む（`list_recent_runs`）。
    """
    async with get_db() as db:
        await db.execute(
            text("""
                INSERT INTO inference_traces (
                    trace_id, run_id, pick_id, symbol, horizon_type, started_at, finished_at,
                    status, stage, stage_status, stage_seq, payload, event_at
                ) VALUES (
                    :trace_id, :run_id, :pick_id, :symbol, :horizon_type, :started_at, :finished_at,
                    :status, :stage, :stage_status, :stage_seq, :payload, :event_at
                )
                """),
            {
                "trace_id": str(uuid.uuid4()),
                "run_id": run_id,
                "pick_id": pick_id,
                "symbol": symbol,
                "horizon_type": horizon_type,
                "started_at": started_at,
                "finished_at": finished_at,
                "status": status,
                "stage": stage,
                "stage_status": stage_status,
                "stage_seq": stage_seq,
                "payload": json.dumps(payload, ensure_ascii=False),
                "event_at": event_at or datetime.now(JST).isoformat(timespec="seconds"),
            },
        )


async def list_trace_events(run_id: str) -> list[dict[str, object]]:
    """指定 run の全ステージイベントを stage_seq 昇順で返す（DAG スナップショット/リプレイ用）."""
    async with get_db() as db:
        result = await db.execute(
            text("SELECT * FROM inference_traces WHERE run_id = :run_id ORDER BY stage_seq ASC, event_at ASC"),
            {"run_id": run_id},
        )
        rows = [dict(r._mapping) for r in result]
    return [_parse_payload(r) for r in rows]


async def list_recent_runs(*, horizon_type: str | None = None, limit: int = 50) -> list[dict[str, object]]:
    """直近の推論実行一覧（run_id ごとに最新イベント1行、新しい順）を返す."""
    clause = "WHERE horizon_type = :horizon_type" if horizon_type else ""
    params: dict[str, object] = {}
    if horizon_type:
        params["horizon_type"] = horizon_type
    async with get_db() as db:
        result = await db.execute(
            text(
                f"SELECT * FROM inference_traces {clause} ORDER BY started_at DESC"  # noqa: S608 - clause は定数のみ  # nosec B608
            ),
            params,
        )
        rows = [dict(r._mapping) for r in result]

    latest_by_run: dict[str, dict[str, object]] = {}
    for row in rows:
        run_id = str(row["run_id"])
        existing = latest_by_run.get(run_id)
        if existing is None or int(row["stage_seq"]) > int(existing["stage_seq"]):  # type: ignore[call-overload]
            latest_by_run[run_id] = row

    ordered = sorted(latest_by_run.values(), key=lambda r: str(r["started_at"]), reverse=True)[:limit]
    return [_parse_payload(r) for r in ordered]


async def list_runs_for_date(date: str, *, horizon_type: str | None = None) -> dict[str, list[dict[str, object]]]:
    """指定日（`started_at` の日付部分）の全 run を `{run_id: [stage_row, ...]}` で返す（🆕 P30）.

    各 run のステージ列は `stage_seq` 昇順（`list_trace_events` と同じ並び）。日次パイプライン
    ログが「LLM深堀りのログ・見解」「3値ブラケット値」「検証ゲートの結果」を run_id ごとに
    再構成するための取得経路。
    """
    clause = "AND horizon_type = :horizon_type" if horizon_type else ""
    params: dict[str, object] = {"date": date}
    if horizon_type:
        params["horizon_type"] = horizon_type
    async with get_db() as db:
        result = await db.execute(
            text(f"""
                SELECT * FROM inference_traces
                WHERE substr(started_at, 1, 10) = :date {clause}
                ORDER BY run_id ASC, stage_seq ASC, event_at ASC
                """),  # noqa: S608 - clause は定数リテラルのみ、値は全てバインド  # nosec B608
            params,
        )
        rows = [dict(r._mapping) for r in result]

    grouped: dict[str, list[dict[str, object]]] = {}
    for row in rows:
        grouped.setdefault(str(row["run_id"]), []).append(_parse_payload(row))
    return grouped


async def attach_pick_id(run_id: str, pick_id: str) -> None:
    """ピック確定後、その run の全イベント行へ pick_id を紐付ける."""
    async with get_db() as db:
        await db.execute(
            text("UPDATE inference_traces SET pick_id = :pick_id WHERE run_id = :run_id"),
            {"pick_id": pick_id, "run_id": run_id},
        )
