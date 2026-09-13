"""`portfolio_signal_shadows`（AI 売買タイミング判定の Gemini 併記）の読み書き（SQLAlchemy async）.

`portfolio_signals` 1件につき Gemini 判定は高々1件（`signal_id` に UNIQUE インデックス）。
表示専用の比較材料であり、承認・却下・実約定の判定フローには一切関与しない。
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import text

from backend.services.db.database import get_db
from backend.services.jst_time import JST


async def insert_shadow(
    *,
    signal_id: str,
    challenger_version: str,
    action: str,
    stop: float,
    target: float,
    confidence: float,
    reasoning: str,
    entry: float | None = None,
) -> str:
    """Gemini（challenger）の売買タイミング判定を1件追加する."""
    shadow_id = str(uuid.uuid4())
    async with get_db() as db:
        await db.execute(
            text(
                """
                INSERT INTO portfolio_signal_shadows (
                    shadow_id, signal_id, challenger_version, action, entry, stop, target,
                    confidence, reasoning, created_at
                ) VALUES (
                    :shadow_id, :signal_id, :challenger_version, :action, :entry, :stop, :target,
                    :confidence, :reasoning, :created_at
                )
                """
            ),
            {
                "shadow_id": shadow_id,
                "signal_id": signal_id,
                "challenger_version": challenger_version,
                "action": action,
                "entry": entry,
                "stop": stop,
                "target": target,
                "confidence": confidence,
                "reasoning": reasoning,
                "created_at": datetime.now(JST).isoformat(timespec="seconds"),
            },
        )
    return shadow_id


async def get_shadows_for_signals(signal_ids: list[str]) -> dict[str, dict[str, object]]:
    """指定した `signal_id` 群に対応する Gemini 判定を `{signal_id: row}` で返す（無ければキー無し）."""
    if not signal_ids:
        return {}
    placeholders = ", ".join(f":id{i}" for i in range(len(signal_ids)))
    params = {f"id{i}": signal_id for i, signal_id in enumerate(signal_ids)}
    async with get_db() as db:
        result = await db.execute(
            text(
                f"SELECT * FROM portfolio_signal_shadows WHERE signal_id IN ({placeholders})"  # noqa: S608 - プレースホルダのみ  # nosec B608
            ),
            params,
        )
        return {str(r._mapping["signal_id"]): dict(r._mapping) for r in result}
