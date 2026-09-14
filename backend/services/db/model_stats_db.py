"""銘柄別モデル（P9/P14）の学習状態を可視化するための集計クエリ（🆕 P15）.

`model_registry_db.py` は CRUD（1行単位の登録・参照）に専念させ、集計専用のクエリは
こちらに分離する。呼び出し元は `services/registry/model_stats_service.py`。
"""

from __future__ import annotations

from sqlalchemy import text

from backend.services.db.database import get_db


async def count_trained_tickers_by_model_type() -> dict[str, int]:
    """モデルタイプ別に、これまで学習履歴がある銘柄数（DISTINCT ticker）を返す.

    `ticker != '__pool__'` で銘柄別モデル（P9）のみを対象にする（断面プールモデルの
    `model_registry` 行は `ticker='__pool__'` で登録されるため除外）。
    """
    async with get_db() as db:
        result = await db.execute(
            text(
                "SELECT model_type, COUNT(DISTINCT ticker) AS n FROM model_registry "
                "WHERE ticker != '__pool__' GROUP BY model_type"
            )
        )
        return {str(r[0]): int(r[1]) for r in result}


async def list_per_ticker_champion_metrics() -> list[dict[str, object]]:
    """全銘柄別レーンの現行 champion について、lane と val_metrics（JSON文字列のまま）を返す.

    `model_champions`（lane ごとに現行 champion 1 行のみ）と `model_registry` を
    `champion_version = version` で結合する。`lane LIKE '%:%'` で銘柄別レーン
    （`f"{model_type}:{ticker}"`）のみに絞る（既存 `_is_per_ticker_lane` と同じ判別方法）。
    呼び出し側（`model_stats_service`）が lane から model_type を取り出し、champion 数の
    集計・val_metrics の JSON デコードによる品質分布の両方に使う。
    """
    async with get_db() as db:
        result = await db.execute(text("""
                SELECT mc.lane AS lane, mr.val_metrics AS val_metrics
                FROM model_champions mc
                JOIN model_registry mr ON mr.version = mc.champion_version
                WHERE mc.lane LIKE '%:%'
                """))
        return [dict(r._mapping) for r in result]


async def get_last_trained_at_by_model_type() -> dict[str, str]:
    """モデルタイプ別に、最後に学習が成功した日時（trained_at の最大値）を返す（🆕 P17）.

    `ticker != '__pool__'` で銘柄別モデルのみを対象にする（`count_trained_tickers_by_model_type`
    と同じ除外理由）。モデルラボの「最終学習日時」表示に使う。
    """
    async with get_db() as db:
        result = await db.execute(
            text(
                "SELECT model_type, MAX(trained_at) AS latest FROM model_registry "
                "WHERE ticker != '__pool__' GROUP BY model_type"
            )
        )
        return {str(r[0]): str(r[1]) for r in result if r[1] is not None}


async def get_training_counts_by_date(since: str) -> list[dict[str, object]]:
    """日別・モデルタイプ別・ステータス別の学習試行件数を返す（学習の推移グラフ用）.

    `training_batch_runs` は追記専用ログのため、日別集計がそのまま時系列になる。
    """
    async with get_db() as db:
        result = await db.execute(
            text(
                "SELECT run_date, model_type, status, COUNT(*) AS n FROM training_batch_runs "
                "WHERE run_date >= :since GROUP BY run_date, model_type, status ORDER BY run_date ASC"
            ),
            {"since": since},
        )
        return [dict(r._mapping) for r in result]
