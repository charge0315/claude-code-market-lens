"""予測台帳（`prediction_ledger`）の書き込み / 参照（CL-1）.

`plans/03_システム設計` §1.1 と §3.1（推論オーケストレータの verify ステージ）に対応。
すべてのピック・売買判定を、予測時点で確定していた情報だけで永続化する。決着記録（P4）が
`pick_id` を FK に参照する。

Alpha Forge の DB は SQLAlchemy async（`services/db/database.py`）。
"""

from __future__ import annotations

import json
import uuid

from sqlalchemy import text

from backend.models.pick import ConfidenceBucket, LedgerEntry, PickSummary
from backend.services.data.data_fetcher import _get_ticker_master
from backend.services.db.database import get_db

# 確度バケットの境界（較正後 confidence 0〜100）。
_HIGH_BUCKET_MIN = 66.0
_MID_BUCKET_MIN = 40.0


def confidence_bucket(confidence: float) -> ConfidenceBucket:
    """較正後の確度（0〜100）を高 / 中 / 低バケットへ分類する."""
    if confidence >= _HIGH_BUCKET_MIN:
        return "high"
    if confidence >= _MID_BUCKET_MIN:
        return "mid"
    return "low"


def new_pick_id() -> str:
    return str(uuid.uuid4())


def new_run_id() -> str:
    return str(uuid.uuid4())


_INSERT = text(
    """
    INSERT INTO prediction_ledger (
        pick_id, run_id, issued_at, horizon_type, symbol, direction,
        entry, stop, target,
        sub_score_technical, sub_score_trend, sub_score_fundamental, sub_score_sentiment,
        composite_score, concordance, confidence_raw, confidence, confidence_bucket,
        feature_snapshot, rationale_struct, rationale_text, model_version, source_contributions,
        is_shadow, created_at
    ) VALUES (
        :pick_id, :run_id, :issued_at, :horizon_type, :symbol, :direction,
        :entry, :stop, :target,
        :st, :str_, :sf, :ss,
        :composite_score, :concordance, :confidence_raw, :confidence, :confidence_bucket,
        :feature_snapshot, :rationale_struct, :rationale_text, :model_version, :source_contributions,
        :is_shadow, :created_at
    )
    """
)


async def insert_pick(entry: LedgerEntry) -> None:
    """予測台帳へ 1 行書き込む."""
    async with get_db() as db:
        await db.execute(
            _INSERT,
            {
                "pick_id": entry.pick_id,
                "run_id": entry.run_id,
                "issued_at": entry.issued_at,
                "horizon_type": entry.horizon_type,
                "symbol": entry.symbol,
                "direction": entry.direction,
                "entry": entry.entry,
                "stop": entry.stop,
                "target": entry.target,
                "st": entry.sub_scores.technical,
                "str_": entry.sub_scores.trend,
                "sf": entry.sub_scores.fundamental,
                "ss": entry.sub_scores.sentiment,
                "composite_score": entry.composite_score,
                "concordance": entry.concordance,
                "confidence_raw": entry.confidence_raw,
                "confidence": entry.confidence,
                "confidence_bucket": entry.confidence_bucket,
                "feature_snapshot": json.dumps(entry.feature_snapshot, ensure_ascii=False),
                "rationale_struct": json.dumps(entry.rationale_struct, ensure_ascii=False),
                "rationale_text": entry.rationale_text,
                "model_version": entry.model_version,
                "source_contributions": json.dumps(entry.source_contributions, ensure_ascii=False),
                "is_shadow": 1 if entry.is_shadow else 0,
                "created_at": entry.created_at,
            },
        )


async def insert_picks(entries: list[LedgerEntry]) -> None:
    """複数ピックをまとめて書き込む（1 実行分）."""
    for e in entries:
        await insert_pick(e)


def _f(value: object) -> float:
    return float(value) if isinstance(value, (int, float)) else 0.0


def _row_to_summary(row: dict[str, object], *, company_name: str | None = None) -> PickSummary:
    return PickSummary(
        pick_id=str(row["pick_id"]),
        issued_at=str(row["issued_at"]),
        horizon_type=str(row["horizon_type"]),
        symbol=str(row["symbol"]),
        company_name=company_name,
        direction=str(row["direction"]),
        entry=_f(row["entry"]),
        stop=_f(row["stop"]),
        target=_f(row["target"]),
        composite_score=_f(row["composite_score"]),
        concordance=_f(row["concordance"]),
        confidence=_f(row["confidence"]),
        confidence_bucket=str(row["confidence_bucket"]),
        rationale_text=str(row["rationale_text"]),
        model_version=str(row["model_version"]),
        source_contributions=json.loads(str(row["source_contributions"] or "{}")),
    )


async def list_picks(
    *,
    horizon_type: str | None = None,
    issued_from: str | None = None,
    issued_to: str | None = None,
    bucket: str | None = None,
    include_shadow: bool = False,
    limit: int = 100,
) -> list[PickSummary]:
    """条件に合うピックを新しい順で返す（`feature_snapshot` は含めない）."""
    clauses: list[str] = []
    params: dict[str, object] = {"limit": limit}
    if not include_shadow:
        clauses.append("is_shadow = 0")
    if horizon_type is not None:
        clauses.append("horizon_type = :horizon_type")
        params["horizon_type"] = horizon_type
    if issued_from is not None:
        clauses.append("issued_at >= :issued_from")
        params["issued_from"] = issued_from
    if issued_to is not None:
        clauses.append("issued_at <= :issued_to")
        params["issued_to"] = issued_to
    if bucket is not None:
        clauses.append("confidence_bucket = :bucket")
        params["bucket"] = bucket

    # clauses は上で組み立てた定数リテラルのみ（外部入力は全て :param バインド）のため注入経路は無い。
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    query = f"SELECT * FROM prediction_ledger {where} ORDER BY issued_at DESC, composite_score DESC LIMIT :limit"  # noqa: S608  # nosec B608 - where は定数リテラルのみ・値は全てバインド
    sql = text(query)
    async with get_db() as db:
        result = await db.execute(sql, params)
        rows = [dict(r._mapping) for r in result]

    # 銘柄名は台帳に保存していない（予測時点の確定情報のみを永続化する方針、CL-1）ため、
    # 表示専用の付加情報として銘柄マスタ（24h キャッシュ）から都度引く。銘柄マスタ未設定
    # （J-Quants 未設定）でもピック一覧の表示自体は失敗させない（None のまま返す）。
    name_by_code = {t.code: t.name for t in await _get_ticker_master()}
    return [_row_to_summary(row, company_name=name_by_code.get(str(row["symbol"]))) for row in rows]


def _dig(payload: object, dotted_path: str) -> object:
    """dict の入れ子から `a.b.c` 形式のパスで値を取り出す（無ければ None）."""
    node = payload
    for key in dotted_path.split("."):
        if not isinstance(node, dict) or key not in node:
            return None
        node = node[key]
    return node


async def list_feature_values(
    feature_path: str, *, since: str, until: str, horizon_type: str | None = None
) -> list[float]:
    """期間内の `feature_snapshot` から dotted path（例: "score_breakdown.technical"）の
    数値を抽出して返す（欠損・非数値はスキップ）. PSI ドリフト検知（N5）が使う.
    """
    clauses = ["is_shadow = 0", "issued_at >= :since", "issued_at < :until"]
    params: dict[str, object] = {"since": since, "until": until}
    if horizon_type is not None:
        clauses.append("horizon_type = :horizon_type")
        params["horizon_type"] = horizon_type
    where = " AND ".join(clauses)
    async with get_db() as db:
        result = await db.execute(
            text(
                f"SELECT feature_snapshot FROM prediction_ledger WHERE {where}"  # noqa: S608  # nosec B608 - where は定数のみ
            ),
            params,
        )
        rows = result.all()

    values: list[float] = []
    for row in rows:
        try:
            snapshot = json.loads(str(row[0]))
        except (TypeError, ValueError):
            continue
        value = _dig(snapshot, feature_path)
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            values.append(float(value))
    return values


async def get_pick(pick_id: str) -> dict[str, object] | None:
    """単一ピックの生行（`feature_snapshot` 含む）を返す."""
    async with get_db() as db:
        result = await db.execute(
            text("SELECT * FROM prediction_ledger WHERE pick_id = :pick_id"), {"pick_id": pick_id}
        )
        row = result.first()
        if row is None:
            return None
        raw = dict(row._mapping)
        for json_col in ("feature_snapshot", "rationale_struct", "source_contributions"):
            raw[json_col] = json.loads(str(raw.get(json_col) or "{}"))
        return raw
