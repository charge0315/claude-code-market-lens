"""api_costs テーブルの読み書き（SQLAlchemy async）.

Market Lens は raw sqlite の `database.py` に同種の関数を持つが、Alpha Forge は
SQLAlchemy async エンジン（`services/db/database.py`）に統一しているため、ここに切り出す。
同日・同機能・同モデルの呼び出しは 1 行へ upsert 加算する。
"""

from __future__ import annotations

from sqlalchemy import text

from backend.services.db.database import get_db

_UPSERT = text(
    """
    INSERT INTO api_costs (
        log_date, feature, model, call_count,
        input_tokens, output_tokens, cache_read_tokens, cache_write_tokens,
        est_cost_usd, pricing_known
    ) VALUES (
        :log_date, :feature, :model, 1,
        :input_tokens, :output_tokens, :cache_read_tokens, :cache_write_tokens,
        :est_cost_usd, :pricing_known
    )
    ON CONFLICT (log_date, feature, model) DO UPDATE SET
        call_count = api_costs.call_count + 1,
        input_tokens = api_costs.input_tokens + excluded.input_tokens,
        output_tokens = api_costs.output_tokens + excluded.output_tokens,
        cache_read_tokens = api_costs.cache_read_tokens + excluded.cache_read_tokens,
        cache_write_tokens = api_costs.cache_write_tokens + excluded.cache_write_tokens,
        est_cost_usd = api_costs.est_cost_usd + excluded.est_cost_usd,
        pricing_known = excluded.pricing_known
    """
)

_ROWS_SINCE = text(
    """
    SELECT log_date, feature, model, call_count, input_tokens, output_tokens,
           cache_read_tokens, cache_write_tokens, est_cost_usd, pricing_known
    FROM api_costs
    WHERE log_date >= :since
    ORDER BY log_date ASC, feature ASC
    """
)


async def insert_api_cost_log(
    *,
    log_date: str,
    feature: str,
    model: str,
    input_tokens: int,
    output_tokens: int,
    cache_read_tokens: int,
    cache_write_tokens: int,
    est_cost_usd: float,
    pricing_known: bool,
) -> None:
    """1 回の LLM 呼び出し分を api_costs へ upsert 加算する."""
    async with get_db() as db:
        await db.execute(
            _UPSERT,
            {
                "log_date": log_date,
                "feature": feature,
                "model": model,
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "cache_read_tokens": cache_read_tokens,
                "cache_write_tokens": cache_write_tokens,
                "est_cost_usd": est_cost_usd,
                "pricing_known": 1 if pricing_known else 0,
            },
        )


async def get_api_cost_rows_since(since: str) -> list[dict[str, object]]:
    """`since`（YYYY-MM-DD）以降の api_costs 行を返す."""
    async with get_db() as db:
        result = await db.execute(_ROWS_SINCE, {"since": since})
        return [dict(row._mapping) for row in result]
