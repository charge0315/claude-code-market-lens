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
    data_source: str | None = None,
) -> None:
    """日次学習バッチの1銘柄分の試行結果を1行追加する（INSERT-only の監査ログ）.

    `data_source`（🆕 P17）は学習に成功した場合のみ `fetch_training_ohlcv` が返す
    実際の採用元（"yfinance"/"jquants"）。失敗行は取得元を特定できないため None のまま。
    """
    async with get_db() as db:
        await db.execute(
            text("""
                INSERT INTO training_batch_runs (run_date, ticker, model_type, status, error, data_source, created_at)
                VALUES (:run_date, :ticker, :model_type, :status, :error, :data_source, :created_at)
                """),
            {
                "run_date": run_date,
                "ticker": ticker,
                "model_type": model_type,
                "status": status,
                "error": error,
                "data_source": data_source,
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
            text("""
                SELECT ticker, MAX(trained_at) AS latest_trained_at
                FROM model_registry
                WHERE model_type = :model_type
                GROUP BY ticker
                """),
            {"model_type": model_type},
        )
        return {str(r[0]): str(r[1]) for r in result}


async def get_latest_failed_at_by_ticker(model_type: str) -> dict[str, str]:
    """指定モデルタイプについて、銘柄ごとの最新の学習失敗日時（created_at）を返す.

    `_select_candidates` が失敗も「最後に試した日時」として扱うために使う。成功日時
    （`model_registry.trained_at`）だけで並べると、上場直後・データ不足で恒常的に失敗する
    銘柄が永久に「未学習」扱いで毎日最優先になり、日次枠を食い潰す（2026-09-21〜24 に発生）。
    """
    async with get_db() as db:
        result = await db.execute(
            text("""
                SELECT ticker, MAX(created_at) AS latest_failed_at
                FROM training_batch_runs
                WHERE model_type = :model_type AND status = 'failed'
                GROUP BY ticker
                """),
            {"model_type": model_type},
        )
        return {str(r[0]): str(r[1]) for r in result}


async def get_latest_data_source_by_model_type() -> dict[str, dict[str, int]]:
    """モデルタイプ別に、銘柄ごとの最新の学習成功試行が使ったデータソースの内訳件数を返す.

    `{"xgboost": {"yfinance": 3900, "jquants": 320}, ...}` の形。銘柄が同一モデルタイプで
    複数回学習されている場合は最新（id が最大）の試行のみを数える（🆕 P17、
    モデルラボの「カバレッジ（データソース別）」表示用）。
    """
    async with get_db() as db:
        result = await db.execute(text("""
                WITH latest AS (
                    SELECT
                        model_type,
                        data_source,
                        ROW_NUMBER() OVER (PARTITION BY model_type, ticker ORDER BY id DESC) AS rn
                    FROM training_batch_runs
                    WHERE status = 'completed' AND data_source IS NOT NULL
                )
                SELECT model_type, data_source, COUNT(*) AS n
                FROM latest
                WHERE rn = 1
                GROUP BY model_type, data_source
                """))
        breakdown: dict[str, dict[str, int]] = {}
        for model_type, data_source, n in result:
            breakdown.setdefault(str(model_type), {})[str(data_source)] = int(n)
        return breakdown
