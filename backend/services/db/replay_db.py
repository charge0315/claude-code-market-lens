"""過去日リプレイ学習の専用台帳（`replay_*` テーブル、🆕 P37）の読み書き.

本番の `prediction_ledger` / `pick_outcomes` とは意図的に別テーブル（`alembic/versions/
0015_replay_tables.py` 参照）。書き込みはすべて冪等にしてあり、途中で落ちたリプレイ日を
やり直しても重複しない（ピックは一意制約 + INSERT OR IGNORE、決着は主キーで上書き）。
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Mapping, Sequence
from datetime import datetime

from sqlalchemy import text

from backend.services.db.database import get_db
from backend.services.jst_time import JST
from backend.services.ledger.outcome_resolver import HorizonOutcome
from backend.services.replay.selection import ReplayPick

_RUN_UPDATABLE = frozenset({"status", "cursor_date", "summary", "error", "pid", "heartbeat_at"})


def _now() -> str:
    return datetime.now(JST).isoformat(timespec="seconds")


def _loads(raw: object) -> object:
    return json.loads(raw) if isinstance(raw, str) and raw else None


def _run_row(row: Mapping[str, object]) -> dict[str, object]:
    out = dict(row)
    out["config"] = _loads(out.get("config")) or {}
    out["summary"] = _loads(out.get("summary"))
    return out


async def create_run(run_id: str, *, start_date: str, end_date: str, config: Mapping[str, object]) -> None:
    now = _now()
    async with get_db() as db:
        await db.execute(
            text("""
                INSERT INTO replay_runs (run_id, status, start_date, end_date, config, created_at, updated_at)
                VALUES (:run_id, 'pending', :start_date, :end_date, :config, :now, :now)
            """),
            {
                "run_id": run_id,
                "start_date": start_date,
                "end_date": end_date,
                "config": json.dumps(config),
                "now": now,
            },
        )


async def update_run(run_id: str, **fields: object) -> None:
    """`_RUN_UPDATABLE` の列だけを更新する（列名は固定集合で検証し SQL へ直接埋め込まない値だけ渡す）."""
    unknown = set(fields) - _RUN_UPDATABLE
    if unknown:
        raise ValueError(f"更新できない列です: {sorted(unknown)}")
    params: dict[str, object] = {"run_id": run_id, "updated_at": _now()}
    assignments = ["updated_at = :updated_at"]
    for key, value in fields.items():
        params[key] = json.dumps(value, ensure_ascii=False) if key == "summary" and value is not None else value
        assignments.append(f"{key} = :{key}")
    sql = f"UPDATE replay_runs SET {', '.join(assignments)} WHERE run_id = :run_id"  # nosec B608 — 列名は _RUN_UPDATABLE の固定集合のみ
    async with get_db() as db:
        await db.execute(text(sql), params)


async def get_run(run_id: str) -> dict[str, object] | None:
    async with get_db() as db:
        result = await db.execute(text("SELECT * FROM replay_runs WHERE run_id = :run_id"), {"run_id": run_id})
        row = result.mappings().first()
    return _run_row(dict(row)) if row is not None else None


async def list_runs(limit: int = 20) -> list[dict[str, object]]:
    async with get_db() as db:
        result = await db.execute(
            text("SELECT * FROM replay_runs ORDER BY created_at DESC LIMIT :limit"), {"limit": limit}
        )
        return [_run_row(dict(r)) for r in result.mappings().all()]


async def insert_picks(run_id: str, picks: Sequence[ReplayPick], *, model_version: str | None) -> None:
    if not picks:
        return
    stmt = text("""
        INSERT OR IGNORE INTO replay_picks (
            pick_id, run_id, horizon_type, issued_at, symbol, rank, entry, stop, target, close,
            composite_score, concordance, direction, recommendation, trend_score, ml_prediction_rate,
            score_breakdown, source_contributions, model_version, resolution_status
        ) VALUES (
            :pick_id, :run_id, :horizon_type, :issued_at, :symbol, :rank, :entry, :stop, :target, :close,
            :composite_score, :concordance, :direction, :recommendation, :trend_score, :ml_prediction_rate,
            :score_breakdown, :source_contributions, :model_version, 'pending'
        )
    """)
    async with get_db() as db:
        for p in picks:
            await db.execute(
                stmt,
                {
                    "pick_id": str(uuid.uuid4()),
                    "run_id": run_id,
                    "horizon_type": p.horizon_type,
                    "issued_at": p.issued_at,
                    "symbol": p.symbol,
                    "rank": p.rank,
                    "entry": p.entry,
                    "stop": p.stop,
                    "target": p.target,
                    "close": p.close,
                    "composite_score": p.composite_score,
                    "concordance": p.concordance,
                    "direction": p.direction,
                    "recommendation": p.recommendation,
                    "trend_score": p.trend_score,
                    "ml_prediction_rate": p.ml_prediction_rate,
                    "score_breakdown": json.dumps(p.score_breakdown, ensure_ascii=False),
                    "source_contributions": json.dumps(p.source_contributions, ensure_ascii=False),
                    "model_version": model_version,
                },
            )


async def list_pending_picks(run_id: str) -> list[dict[str, object]]:
    async with get_db() as db:
        result = await db.execute(
            text("""
                SELECT pick_id, horizon_type, issued_at, symbol, entry, stop, target, model_version
                FROM replay_picks WHERE run_id = :run_id AND resolution_status = 'pending'
                ORDER BY issued_at, horizon_type, rank
            """),
            {"run_id": run_id},
        )
        return [dict(r) for r in result.mappings().all()]


async def record_outcomes(
    run_id: str, pick_id: str, outcomes: Sequence[HorizonOutcome], *, resolved_on: str, status: str
) -> None:
    """成熟したホライズンの決着を上書き保存し、ピックの解決状態を更新する.

    `status` が pending 以外（filled = 全ホライズン決着 / unfilled / no_data）ならそのピックは完了。
    """
    stmt = text("""
        INSERT OR REPLACE INTO replay_outcomes (
            pick_id, horizon_days, run_id, realized_return, win, hit_stop, hit_target, first_hit,
            mfe, mae, benchmark_return, excess_return, resolved_on
        ) VALUES (
            :pick_id, :horizon_days, :run_id, :realized_return, :win, :hit_stop, :hit_target, :first_hit,
            :mfe, :mae, :benchmark_return, :excess_return, :resolved_on
        )
    """)
    async with get_db() as db:
        for o in outcomes:
            await db.execute(
                stmt,
                {
                    "pick_id": pick_id,
                    "horizon_days": o.horizon_days,
                    "run_id": run_id,
                    "realized_return": o.realized_return,
                    "win": int(o.win),
                    "hit_stop": int(o.hit_stop),
                    "hit_target": int(o.hit_target),
                    "first_hit": o.first_hit,
                    "mfe": o.mfe,
                    "mae": o.mae,
                    "benchmark_return": o.benchmark_return,
                    "excess_return": o.excess_return,
                    "resolved_on": resolved_on,
                },
            )
        await db.execute(
            text("UPDATE replay_picks SET resolution_status = :status WHERE pick_id = :pick_id"),
            {"status": status, "pick_id": pick_id},
        )


async def list_resolved(run_id: str, *, horizon_days: int) -> list[dict[str, object]]:
    """指定ホライズンの決着済みピック（学習・集計用）。JSON 列は dict へ戻して返す."""
    async with get_db() as db:
        result = await db.execute(
            text("""
                SELECT p.pick_id, p.horizon_type, p.issued_at, p.symbol, p.composite_score, p.concordance,
                       p.direction, p.recommendation, p.trend_score, p.ml_prediction_rate,
                       p.score_breakdown, p.source_contributions,
                       o.horizon_days, o.realized_return, o.win, o.hit_stop, o.hit_target, o.first_hit,
                       o.mfe, o.mae, o.benchmark_return, o.excess_return
                FROM replay_outcomes o JOIN replay_picks p ON p.pick_id = o.pick_id
                WHERE o.run_id = :run_id AND o.horizon_days = :horizon_days
                ORDER BY p.issued_at
            """),
            {"run_id": run_id, "horizon_days": horizon_days},
        )
        rows = [dict(r) for r in result.mappings().all()]
    for row in rows:
        row["score_breakdown"] = _loads(row["score_breakdown"]) or {}
        row["source_contributions"] = _loads(row["source_contributions"]) or {}
        row["win"] = bool(row["win"])
    return rows


async def insert_retrain(run_id: str, *, trained_on: str, model_version: str, metrics: Mapping[str, object]) -> None:
    async with get_db() as db:
        await db.execute(
            text("""
                INSERT OR REPLACE INTO replay_retrains (run_id, trained_on, model_version, metrics)
                VALUES (:run_id, :trained_on, :model_version, :metrics)
            """),
            {
                "run_id": run_id,
                "trained_on": trained_on,
                "model_version": model_version,
                "metrics": json.dumps(metrics),
            },
        )


async def list_retrains(run_id: str) -> list[dict[str, object]]:
    async with get_db() as db:
        result = await db.execute(
            text("""
                SELECT trained_on, model_version, metrics FROM replay_retrains
                WHERE run_id = :run_id ORDER BY trained_on
            """),
            {"run_id": run_id},
        )
        rows = [dict(r) for r in result.mappings().all()]
    for row in rows:
        row["metrics"] = _loads(row["metrics"]) or {}
    return rows


async def count_picks(run_id: str) -> dict[str, int]:
    async with get_db() as db:
        result = await db.execute(
            text("SELECT horizon_type, COUNT(*) AS n FROM replay_picks WHERE run_id = :run_id GROUP BY horizon_type"),
            {"run_id": run_id},
        )
        return {str(r["horizon_type"]): int(r["n"]) for r in result.mappings().all()}
