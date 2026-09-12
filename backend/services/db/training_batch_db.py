"""`training_batch_runs` テーブルの読み書き（銘柄別モデル日次学習バッチ、P9）.

Market Lens `backend/services/database.py` の training_batch_runs 関連 CRUD から移植。
`get_manually_trained_tickers`（手動学習/チューニングされた銘柄の保護）は Alpha Forge に
手動学習 UI が無いため移植しない（`plans/04_タスクリスト.md` P9）。
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import text

from backend.services.db.database import get_db
from backend.services.jst_time import JST


async def insert_training_batch_run(
    *,
    run_date: str,
    ticker: str,
    model_type: str,
    status: str,
    error: str | None = None,
) -> None:
    """日次学習バッチの1銘柄分の試行結果を1行追加する（INSERT-only の監査ログ）."""
    async with get_db() as db:
        await db.execute(
            text(
                """
                INSERT INTO training_batch_runs (run_date, ticker, model_type, status, error, created_at)
                VALUES (:run_date, :ticker, :model_type, :status, :error, :created_at)
                """
            ),
            {
                "run_date": run_date,
                "ticker": ticker,
                "model_type": model_type,
                "status": status,
                "error": error,
                "created_at": datetime.now(JST).isoformat(timespec="seconds"),
            },
        )


async def get_attempted_tickers(run_date: str, model_type: str) -> set[str]:
    """指定日・モデルタイプで既に試行済み（成功/失敗いずれも）の銘柄コード集合を返す.

    4系統（xgboost/random_forest/lstm/transformer）は独立した当日上限で動くため、
    model_type は必須（省略すると他系統の試行が候補を食い潰してしまう）。
    """
    async with get_db() as db:
        result = await db.execute(
            text(
                "SELECT DISTINCT ticker FROM training_batch_runs "
                "WHERE run_date = :run_date AND model_type = :model_type"
            ),
            {"run_date": run_date, "model_type": model_type},
        )
        return {str(r[0]) for r in result}


async def get_latest_trained_at_by_ticker(model_type: str) -> dict[str, str]:
    """指定モデルタイプについて、銘柄ごとの最新学習日時（trained_at）を返す.

    `per_ticker_training_service._select_candidates` が「未学習の銘柄」「最も学習が
    古い銘柄」を優先選定するために使う。`model_registry` は学習のたびに新規行を
    追加する（更新しない）ため、銘柄ごとに MAX を取る。
    """
    async with get_db() as db:
        result = await db.execute(
            text(
                """
                SELECT ticker, MAX(trained_at) AS latest_trained_at
                FROM model_registry
                WHERE model_type = :model_type
                GROUP BY ticker
                """
            ),
            {"model_type": model_type},
        )
        return {str(r[0]): str(r[1]) for r in result}
