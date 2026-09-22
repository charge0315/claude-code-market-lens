"""`shadow_predictions` の読み書き（🆕 P12、マルチLLM判定）.

`shadow_predictions` テーブルは P1 のベースラインマイグレーション（`0001_baseline.py`）で
ML challenger 用に定義済みだったが未使用のまま残っていた。今回、Gemini による「別視点の
LLM 判定」を記録する用途に転用する（`challenger_version` に `"gemini:<model名>"` を入れる
ことで、将来 ML challenger を実装する際も同じテーブルを共有できる）。

このテーブルは表示専用の比較材料であり、`model_promotions`/`model_champions` の昇格判定・
確度較正には一切関与しない。
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


async def insert_shadow_prediction(
    *,
    pick_id: str | None,
    run_id: str,
    challenger_version: str,
    symbol: str,
    horizon_type: str,
    direction: str,
    entry: float,
    stop: float,
    target: float,
    confidence_raw: float,
    confidence: float,
    payload: dict[str, object],
    issued_at: str | None = None,
) -> None:
    """1件の challenger 判定（Gemini 等）を1行追加する（INSERT-only）."""
    async with get_db() as db:
        await db.execute(
            text("""
                INSERT INTO shadow_predictions (
                    shadow_id, pick_id, run_id, challenger_version, symbol, horizon_type,
                    issued_at, direction, entry, stop, target, confidence_raw, confidence, payload
                ) VALUES (
                    :shadow_id, :pick_id, :run_id, :challenger_version, :symbol, :horizon_type,
                    :issued_at, :direction, :entry, :stop, :target, :confidence_raw, :confidence, :payload
                )
                """),
            {
                "shadow_id": str(uuid.uuid4()),
                "pick_id": pick_id,
                "run_id": run_id,
                "challenger_version": challenger_version,
                "symbol": symbol,
                "horizon_type": horizon_type,
                "issued_at": issued_at or datetime.now(JST).isoformat(timespec="seconds"),
                "direction": direction,
                "entry": entry,
                "stop": stop,
                "target": target,
                "confidence_raw": confidence_raw,
                "confidence": confidence,
                "payload": json.dumps(payload, ensure_ascii=False),
            },
        )


async def list_shadow_predictions_for_pick(pick_id: str) -> list[dict[str, object]]:
    """指定ピックに紐づく全 challenger 判定を issued_at 昇順で返す（ピック詳細ポップアップ用）."""
    async with get_db() as db:
        result = await db.execute(
            text("SELECT * FROM shadow_predictions WHERE pick_id = :pick_id ORDER BY issued_at ASC"),
            {"pick_id": pick_id},
        )
        rows = [dict(r._mapping) for r in result]
    return [_parse_payload(r) for r in rows]


async def list_shadow_predictions_for_run(run_id: str) -> list[dict[str, object]]:
    """指定 run に紐づく全 challenger 判定を issued_at 昇順で返す（🆕 P36、`pick_id` 未確定の
    オンデマンド推論トレース表示用。`list_shadow_predictions_for_pick` の run_id 版）."""
    async with get_db() as db:
        result = await db.execute(
            text("SELECT * FROM shadow_predictions WHERE run_id = :run_id ORDER BY issued_at ASC"),
            {"run_id": run_id},
        )
        rows = [dict(r._mapping) for r in result]
    return [_parse_payload(r) for r in rows]


async def list_shadow_predictions(
    *,
    horizon_type: str | None = None,
    issued_from: str | None = None,
    issued_to: str | None = None,
    limit: int = 50,
) -> list[dict[str, object]]:
    """条件で絞り込んだ challenger 判定を新しい順で返す（🆕 P25、Gemini ピック一覧用）."""
    clauses: list[str] = []
    params: dict[str, object] = {"limit": limit}
    if horizon_type is not None:
        clauses.append("horizon_type = :horizon_type")
        params["horizon_type"] = horizon_type
    if issued_from is not None:
        clauses.append("issued_at >= :issued_from")
        params["issued_from"] = issued_from
    if issued_to is not None:
        clauses.append("issued_at <= :issued_to")
        params["issued_to"] = issued_to

    # clauses は定数リテラルのみ（外部入力は全て :param バインド）のため注入経路は無い。
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    query = f"SELECT * FROM shadow_predictions {where} ORDER BY issued_at DESC LIMIT :limit"  # noqa: S608  # nosec B608 - where は定数リテラルのみ・値は全てバインド
    async with get_db() as db:
        result = await db.execute(text(query), params)
        rows = [dict(r._mapping) for r in result]
    return [_parse_payload(r) for r in rows]
