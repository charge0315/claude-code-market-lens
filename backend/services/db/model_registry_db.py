"""`model_registry` / `model_champions` / `model_promotions` の読み書き（SQLAlchemy async）.

`plans/03_システム設計` §1.4（N1）。
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from datetime import datetime

from sqlalchemy import text

from backend.services.db.database import get_db
from backend.services.jst_time import JST


async def upsert_model(
    *,
    version: str,
    model_type: str,
    ticker: str = "__pool__",
    objective: str = "classification",
    artifact_path: str = "",
    val_metrics: Mapping[str, object] | None = None,
    feature_list: Sequence[str] | None = None,
    trained_at: str | None = None,
) -> None:
    """モデル（ここでは recommender+LLM の構成スナップショット）を登録 / 更新する."""
    async with get_db() as db:
        await db.execute(
            text(
                """
                INSERT INTO model_registry (
                    version, model_type, ticker, objective, trained_at, artifact_path,
                    val_metrics, feature_list
                ) VALUES (
                    :version, :model_type, :ticker, :objective, :trained_at, :artifact_path,
                    :val_metrics, :feature_list
                )
                ON CONFLICT (version) DO UPDATE SET
                    val_metrics = excluded.val_metrics,
                    feature_list = excluded.feature_list
                """
            ),
            {
                "version": version,
                "model_type": model_type,
                "ticker": ticker,
                "objective": objective,
                "trained_at": trained_at or datetime.now(JST).isoformat(timespec="seconds"),
                "artifact_path": artifact_path,
                "val_metrics": json.dumps(val_metrics or {}, ensure_ascii=False),
                "feature_list": json.dumps(feature_list or [], ensure_ascii=False),
            },
        )


async def get_model(version: str) -> dict[str, object] | None:
    """指定バージョンの登録情報を返す（無ければ None）."""
    async with get_db() as db:
        row = (
            await db.execute(text("SELECT * FROM model_registry WHERE version = :version"), {"version": version})
        ).first()
        return dict(row._mapping) if row is not None else None


async def list_versions_by_model_type(model_type: str) -> list[str]:
    """指定 `model_type`（= lane を符号化したもの）で登録済みの全バージョンを返す."""
    async with get_db() as db:
        result = await db.execute(
            text("SELECT version FROM model_registry WHERE model_type = :model_type ORDER BY trained_at ASC"),
            {"model_type": model_type},
        )
        return [str(r[0]) for r in result]


async def get_champion(lane: str) -> str | None:
    """指定系統（lane）の現行 champion バージョンを返す（未設定なら None）."""
    async with get_db() as db:
        row = (
            await db.execute(text("SELECT champion_version FROM model_champions WHERE lane = :lane"), {"lane": lane})
        ).first()
        return str(row[0]) if row is not None else None


async def set_champion(lane: str, version: str, *, promoted_by: str = "manual") -> None:
    """系統の champion を差し替える（`model_registry` に存在するバージョンのみ許可、FK 制約）."""
    async with get_db() as db:
        await db.execute(
            text(
                """
                INSERT INTO model_champions (lane, champion_version, promoted_at, promoted_by)
                VALUES (:lane, :version, :promoted_at, :promoted_by)
                ON CONFLICT (lane) DO UPDATE SET
                    champion_version = excluded.champion_version,
                    promoted_at = excluded.promoted_at,
                    promoted_by = excluded.promoted_by
                """
            ),
            {
                "lane": lane,
                "version": version,
                "promoted_at": datetime.now(JST).isoformat(timespec="seconds"),
                "promoted_by": promoted_by,
            },
        )


async def list_champions() -> list[dict[str, object]]:
    """全系統の現行 champion 一覧を返す."""
    async with get_db() as db:
        result = await db.execute(text("SELECT * FROM model_champions ORDER BY lane ASC"))
        return [dict(r._mapping) for r in result]


async def insert_promotion(
    *,
    promotion_id: str,
    lane: str,
    challenger_version: str,
    champion_version: str | None,
    holdout_delta: float,
    calib_regressed: bool,
    paper_perf_delta: float,
    paper_days: int,
    verdict: str,
    rationale: dict[str, object],
    evaluated_at: str | None = None,
) -> None:
    """昇格ゲートの判定結果を 1 行追加する（`applied=0` で作成、適用は別 API）."""
    async with get_db() as db:
        await db.execute(
            text(
                """
                INSERT INTO model_promotions (
                    promotion_id, lane, challenger_version, champion_version, evaluated_at,
                    holdout_delta, calib_regressed, paper_perf_delta, paper_days, verdict,
                    applied, rationale
                ) VALUES (
                    :promotion_id, :lane, :challenger_version, :champion_version, :evaluated_at,
                    :holdout_delta, :calib_regressed, :paper_perf_delta, :paper_days, :verdict,
                    0, :rationale
                )
                """
            ),
            {
                "promotion_id": promotion_id,
                "lane": lane,
                "challenger_version": challenger_version,
                "champion_version": champion_version,
                "evaluated_at": evaluated_at or datetime.now(JST).isoformat(timespec="seconds"),
                "holdout_delta": holdout_delta,
                "calib_regressed": 1 if calib_regressed else 0,
                "paper_perf_delta": paper_perf_delta,
                "paper_days": paper_days,
                "verdict": verdict,
                "rationale": json.dumps(rationale, ensure_ascii=False),
            },
        )


async def get_promotion(promotion_id: str) -> dict[str, object] | None:
    """1 件の昇格判定ログを返す（無ければ None）."""
    async with get_db() as db:
        row = (
            await db.execute(
                text("SELECT * FROM model_promotions WHERE promotion_id = :promotion_id"),
                {"promotion_id": promotion_id},
            )
        ).first()
        return dict(row._mapping) if row is not None else None


async def list_promotions(*, lane: str | None = None, limit: int = 100) -> list[dict[str, object]]:
    """昇格判定ログを新しい順に返す."""
    clause = "WHERE lane = :lane" if lane else ""
    params: dict[str, object] = {"limit": limit}
    if lane:
        params["lane"] = lane
    async with get_db() as db:
        result = await db.execute(
            text(
                f"SELECT * FROM model_promotions {clause} ORDER BY evaluated_at DESC LIMIT :limit"  # noqa: S608  # nosec B608 - clause は定数のみ
            ),
            params,
        )
        return [dict(r._mapping) for r in result]


async def mark_promotion_applied(promotion_id: str) -> None:
    """昇格判定を適用済みにする（人手承認 API からのみ呼ぶ）."""
    async with get_db() as db:
        await db.execute(
            text("UPDATE model_promotions SET applied = 1 WHERE promotion_id = :promotion_id"),
            {"promotion_id": promotion_id},
        )
