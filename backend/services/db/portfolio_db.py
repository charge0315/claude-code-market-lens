"""`portfolios`（保有銘柄）の読み書き（SQLAlchemy async）.

`plans/03_システム設計` §1.7。同一銘柄でも取得日が異なれば別ロット（`UNIQUE(symbol,
acquired_at)`）として扱う。
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import text

from backend.services.db.database import get_db
from backend.services.jst_time import JST


async def insert_holding(*, symbol: str, quantity: int, avg_cost: float, acquired_at: str) -> str:
    """保有銘柄（1 ロット）を追加し `holding_id` を返す.

    同一 (symbol, acquired_at) が既に存在する場合は `UNIQUE` 制約違反（呼び出し側で捕捉）。
    """
    holding_id = str(uuid.uuid4())
    now = datetime.now(JST).isoformat(timespec="seconds")
    async with get_db() as db:
        await db.execute(
            text(
                """
                INSERT INTO portfolios (holding_id, symbol, quantity, avg_cost, acquired_at, created_at, updated_at)
                VALUES (:holding_id, :symbol, :quantity, :avg_cost, :acquired_at, :created_at, :updated_at)
                """
            ),
            {
                "holding_id": holding_id,
                "symbol": symbol,
                "quantity": quantity,
                "avg_cost": avg_cost,
                "acquired_at": acquired_at,
                "created_at": now,
                "updated_at": now,
            },
        )
    return holding_id


async def list_holdings() -> list[dict[str, object]]:
    """全保有ロットを取得日昇順で返す."""
    async with get_db() as db:
        result = await db.execute(text("SELECT * FROM portfolios ORDER BY acquired_at ASC"))
        return [dict(r._mapping) for r in result]


async def get_holding(holding_id: str) -> dict[str, object] | None:
    """1 ロットを返す（無ければ None）."""
    async with get_db() as db:
        result = await db.execute(
            text("SELECT * FROM portfolios WHERE holding_id = :holding_id"), {"holding_id": holding_id}
        )
        row = result.first()
        return dict(row._mapping) if row is not None else None


async def update_holding(holding_id: str, *, quantity: int, avg_cost: float) -> bool:
    """株数・平均取得単価を更新する。対象行が無ければ False."""
    now = datetime.now(JST).isoformat(timespec="seconds")
    async with get_db() as db:
        result = await db.execute(
            text(
                """
                UPDATE portfolios SET quantity = :quantity, avg_cost = :avg_cost, updated_at = :updated_at
                WHERE holding_id = :holding_id
                """
            ),
            {"holding_id": holding_id, "quantity": quantity, "avg_cost": avg_cost, "updated_at": now},
        )
        return result.rowcount > 0


async def delete_holding(holding_id: str) -> bool:
    """1 ロットを削除する。対象行が無ければ False."""
    async with get_db() as db:
        result = await db.execute(
            text("DELETE FROM portfolios WHERE holding_id = :holding_id"), {"holding_id": holding_id}
        )
        return result.rowcount > 0
