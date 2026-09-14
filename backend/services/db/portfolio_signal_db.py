"""`portfolio_signals`（AI 売買タイミング判定の HITL 承認キュー）の読み書き（SQLAlchemy async）.

`plans/03_システム設計` §1.7。判定は `status="proposed"` で作成され、人手承認 API
（`approve`/`reject`/`report-fill`）でのみ遷移する（CLAUDE.md「承認制」）。
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import text

from backend.services.db.database import get_db
from backend.services.jst_time import JST


async def insert_signal(
    *,
    symbol: str,
    action: str,
    stop: float,
    target: float,
    confidence: float,
    rationale: str,
    entry: float | None = None,
    evaluated_at: str | None = None,
) -> str:
    """AI 売買タイミング判定を1件追加する（`status="proposed"` 固定）."""
    signal_id = str(uuid.uuid4())
    async with get_db() as db:
        await db.execute(
            text("""
                INSERT INTO portfolio_signals (
                    signal_id, symbol, evaluated_at, action, entry, stop, target,
                    confidence, rationale, status, fill_report
                ) VALUES (
                    :signal_id, :symbol, :evaluated_at, :action, :entry, :stop, :target,
                    :confidence, :rationale, 'proposed', NULL
                )
                """),
            {
                "signal_id": signal_id,
                "symbol": symbol,
                "evaluated_at": evaluated_at or datetime.now(JST).isoformat(timespec="seconds"),
                "action": action,
                "entry": entry,
                "stop": stop,
                "target": target,
                "confidence": confidence,
                "rationale": rationale,
            },
        )
    return signal_id


async def list_signals(*, status: str | None = None, limit: int = 100) -> list[dict[str, object]]:
    """判定履歴を新しい順で返す."""
    clause = "WHERE status = :status" if status else ""
    params: dict[str, object] = {"limit": limit}
    if status:
        params["status"] = status
    async with get_db() as db:
        result = await db.execute(
            text(
                f"SELECT * FROM portfolio_signals {clause} ORDER BY evaluated_at DESC LIMIT :limit"  # noqa: S608 - clause は定数のみ  # nosec B608
            ),
            params,
        )
        return [dict(r._mapping) for r in result]


async def list_signals_for_date(run_date: str) -> list[dict[str, object]]:
    """指定日（`evaluated_at` の日付部分）に評価された判定を全件返す（EOD レビュー用）."""
    async with get_db() as db:
        result = await db.execute(
            text("SELECT * FROM portfolio_signals WHERE substr(evaluated_at, 1, 10) = :run_date ORDER BY evaluated_at"),
            {"run_date": run_date},
        )
        return [dict(r._mapping) for r in result]


async def get_signal(signal_id: str) -> dict[str, object] | None:
    """1件を返す（無ければ None）."""
    async with get_db() as db:
        result = await db.execute(
            text("SELECT * FROM portfolio_signals WHERE signal_id = :signal_id"), {"signal_id": signal_id}
        )
        row = result.first()
        return dict(row._mapping) if row is not None else None


async def set_status(signal_id: str, status: str) -> bool:
    """`status` を更新する（`proposed`→`approved`/`rejected` の遷移用）。対象行が無ければ False."""
    async with get_db() as db:
        result = await db.execute(
            text("UPDATE portfolio_signals SET status = :status WHERE signal_id = :signal_id"),
            {"signal_id": signal_id, "status": status},
        )
        return result.rowcount > 0


async def set_fill_report(signal_id: str, fill_report_json: str) -> bool:
    """実約定結果を記録し `status="executed"` にする。対象行が無ければ False."""
    async with get_db() as db:
        result = await db.execute(
            text("""
                UPDATE portfolio_signals SET status = 'executed', fill_report = :fill_report
                WHERE signal_id = :signal_id
                """),
            {"signal_id": signal_id, "fill_report": fill_report_json},
        )
        return result.rowcount > 0
