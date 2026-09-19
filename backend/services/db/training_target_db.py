"""`training_target_settings` / `training_target_tickers` の読み書き（SQLAlchemy async）.

🆕 学習対象設定。`training_batch_db.py` / `model_registry_db.py` と同水準の薄い CRUD。
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime

from sqlalchemy import text

from backend.services.db.database import get_db
from backend.services.jst_time import JST

_SETTINGS_ID = "default"


async def get_training_settings() -> dict[str, object] | None:
    """学習対象設定の唯一の行を返す（未保存なら None、呼び出し側が既定値にフォールバックする）."""
    async with get_db() as db:
        row = (
            await db.execute(text("SELECT * FROM training_target_settings WHERE id = :id"), {"id": _SETTINGS_ID})
        ).first()
        return dict(row._mapping) if row is not None else None


async def upsert_training_settings(*, target_mode: str, max_parallel_workers: int) -> None:
    """学習対象モード・並列数上限を保存する（`model_champions` と同じ Upsert パターン）."""
    async with get_db() as db:
        await db.execute(
            text("""
                INSERT INTO training_target_settings (id, target_mode, max_parallel_workers, updated_at)
                VALUES (:id, :target_mode, :max_parallel_workers, :updated_at)
                ON CONFLICT (id) DO UPDATE SET
                    target_mode = excluded.target_mode,
                    max_parallel_workers = excluded.max_parallel_workers,
                    updated_at = excluded.updated_at
                """),
            {
                "id": _SETTINGS_ID,
                "target_mode": target_mode,
                "max_parallel_workers": max_parallel_workers,
                "updated_at": datetime.now(JST).isoformat(timespec="seconds"),
            },
        )


async def list_custom_tickers() -> list[str]:
    """カスタムリストの銘柄コード一覧を返す（追加日昇順）."""
    async with get_db() as db:
        result = await db.execute(text("SELECT ticker FROM training_target_tickers ORDER BY added_at ASC"))
        return [str(r[0]) for r in result]


async def get_custom_ticker_added_at_map() -> dict[str, str]:
    """カスタムリストの銘柄ごとの追加日時を返す（差分学習の優先度判定用）."""
    async with get_db() as db:
        result = await db.execute(text("SELECT ticker, added_at FROM training_target_tickers"))
        return {str(r[0]): str(r[1]) for r in result}


async def add_custom_tickers(tickers: Sequence[str]) -> None:
    """カスタムリストへ銘柄を追加する（既存銘柄の再追加では `added_at` を巻き戻さない）."""
    if not tickers:
        return
    now = datetime.now(JST).isoformat(timespec="seconds")
    async with get_db() as db:
        for ticker in tickers:
            await db.execute(
                text("""
                    INSERT INTO training_target_tickers (ticker, added_at)
                    VALUES (:ticker, :added_at)
                    ON CONFLICT (ticker) DO NOTHING
                    """),
                {"ticker": ticker, "added_at": now},
            )


async def replace_custom_tickers(tickers: Sequence[str]) -> None:
    """カスタムリストを指定集合に全置換する（ポップアップダイアログの保存で使う）.

    既存銘柄は `added_at` を保持したまま残し、新規銘柄のみ現在時刻で追加する
    （要件6の差分学習優先度が、既存銘柄の再保存で不当にリセットされないようにするため）。
    """
    wanted = set(tickers)
    existing = set(await list_custom_tickers())
    to_add = sorted(wanted - existing)
    to_remove = sorted(existing - wanted)
    await add_custom_tickers(to_add)
    if to_remove:
        async with get_db() as db:
            for ticker in to_remove:
                await db.execute(text("DELETE FROM training_target_tickers WHERE ticker = :ticker"), {"ticker": ticker})
