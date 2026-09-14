"""`pick_outcomes` テーブルの読み書き（SQLAlchemy async）.

`plans/03_システム設計` §1.2。1 ピックにつき複数ホライズン（短期 1/2/3、中長期 5/20/60）
の決着行を持つ。`(pick_id, horizon_days)` の一意制約で upsert する。
"""

from __future__ import annotations

import uuid

from sqlalchemy import text

from backend.services.db.database import get_db

_UPSERT = text("""
    INSERT INTO pick_outcomes (
        outcome_id, pick_id, horizon_days, resolved_at, realized_return, win,
        hit_stop, hit_target, first_hit, mfe, mae, benchmark_return, excess_return,
        confidence_bucket, direction
    ) VALUES (
        :outcome_id, :pick_id, :horizon_days, :resolved_at, :realized_return, :win,
        :hit_stop, :hit_target, :first_hit, :mfe, :mae, :benchmark_return, :excess_return,
        :confidence_bucket, :direction
    )
    ON CONFLICT (pick_id, horizon_days) DO UPDATE SET
        resolved_at = excluded.resolved_at,
        realized_return = excluded.realized_return,
        win = excluded.win,
        hit_stop = excluded.hit_stop,
        hit_target = excluded.hit_target,
        first_hit = excluded.first_hit,
        mfe = excluded.mfe,
        mae = excluded.mae,
        benchmark_return = excluded.benchmark_return,
        excess_return = excluded.excess_return,
        confidence_bucket = excluded.confidence_bucket,
        direction = excluded.direction
    """)


async def upsert_outcome(
    *,
    pick_id: str,
    horizon_days: int,
    resolved_at: str,
    realized_return: float,
    win: bool,
    hit_stop: bool,
    hit_target: bool,
    first_hit: str,
    mfe: float,
    mae: float,
    benchmark_return: float,
    excess_return: float,
    confidence_bucket: str,
    direction: str,
) -> None:
    """決着行を 1 件 upsert する."""
    async with get_db() as db:
        await db.execute(
            _UPSERT,
            {
                "outcome_id": str(uuid.uuid4()),
                "pick_id": pick_id,
                "horizon_days": horizon_days,
                "resolved_at": resolved_at,
                "realized_return": realized_return,
                "win": 1 if win else 0,
                "hit_stop": 1 if hit_stop else 0,
                "hit_target": 1 if hit_target else 0,
                "first_hit": first_hit,
                "mfe": mfe,
                "mae": mae,
                "benchmark_return": benchmark_return,
                "excess_return": excess_return,
                "confidence_bucket": confidence_bucket,
                "direction": direction,
            },
        )


async def list_unresolved_picks(*, issued_before: str, limit: int = 50) -> list[dict[str, object]]:
    """まだ決着行を 1 つも持たず、issued_at が `issued_before` より前のピック（本番のみ）を返す."""
    async with get_db() as db:
        result = await db.execute(
            text("""
                SELECT p.* FROM prediction_ledger p
                WHERE p.is_shadow = 0
                  AND p.issued_at < :issued_before
                  AND NOT EXISTS (SELECT 1 FROM pick_outcomes o WHERE o.pick_id = p.pick_id)
                ORDER BY p.issued_at ASC
                LIMIT :limit
                """),
            {"issued_before": issued_before, "limit": limit},
        )
        return [dict(r._mapping) for r in result]


async def list_outcomes(pick_id: str) -> list[dict[str, object]]:
    """指定ピックの決着行を horizon 昇順で返す."""
    async with get_db() as db:
        result = await db.execute(
            text("SELECT * FROM pick_outcomes WHERE pick_id = :pick_id ORDER BY horizon_days ASC"),
            {"pick_id": pick_id},
        )
        return [dict(r._mapping) for r in result]


async def list_resolved_for_eval(*, horizon_days: int, since: str | None = None) -> list[dict[str, object]]:
    """評価集計用に、決着済みピックの (台帳 + 決着) を結合して返す（指定ホライズン）."""
    clause = "AND p.issued_at >= :since" if since else ""
    params: dict[str, object] = {"horizon_days": horizon_days}
    if since:
        params["since"] = since
    async with get_db() as db:
        result = await db.execute(
            text(f"""
                SELECT
                    p.pick_id, p.horizon_type, p.issued_at, p.symbol, p.direction AS pick_direction,
                    p.composite_score, p.confidence, p.confidence_raw, p.confidence_bucket, p.model_version,
                    p.entry, p.stop, p.target, p.source_contributions,
                    o.horizon_days, o.realized_return, o.win, o.first_hit, o.excess_return,
                    o.mfe, o.mae
                FROM pick_outcomes o
                JOIN prediction_ledger p ON p.pick_id = o.pick_id
                WHERE o.horizon_days = :horizon_days {clause}
                ORDER BY p.issued_at ASC
                """),  # noqa: S608 - clause は定数リテラルのみ、値は全てバインド  # nosec B608
            params,
        )
        return [dict(r._mapping) for r in result]


async def cohort_winrate(
    *, confidence_bucket: str | None = None, direction: str | None = None, horizon_days: int = 20
) -> tuple[float | None, int]:
    """確度バケット / 方向コホートの実測勝率（excess_return > 0 の比率）と約定件数を返す.

    実測勝率ゲート（E3、ピックパイプライン P3d のハード除外）が参照する。台帳が薄いうちは
    件数が小さく、ゲート発動条件（min_sample）に満たない。
    """
    clauses = ["o.horizon_days = :horizon_days"]
    params: dict[str, object] = {"horizon_days": horizon_days}
    if confidence_bucket is not None:
        clauses.append("o.confidence_bucket = :cb")
        params["cb"] = confidence_bucket
    if direction is not None:
        clauses.append("o.direction = :dir")
        params["dir"] = direction
    where = " AND ".join(clauses)
    async with get_db() as db:
        result = await db.execute(
            text(
                f"SELECT excess_return FROM pick_outcomes o WHERE {where}"  # noqa: S608  # nosec B608 - where は定数のみ
            ),
            params,
        )
        vals = [float(r[0]) for r in result if r[0] is not None]
    if not vals:
        return None, 0
    return round(sum(1 for v in vals if v > 0) / len(vals), 4), len(vals)
