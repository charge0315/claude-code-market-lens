"""`source_ablations` テーブルの読み書き（SQLAlchemy async）.

`plans/03_システム設計` §1.3。テーブル自体は `0001_baseline` で定義済みだったが書き込む実装が
存在しなかった（🆕 P29 で初実装）。四半期ごと、各情報源（`excluded_source`）を除外して
再学習した場合のホールドアウト指標差分（`metric_delta` = 除外時 − 全部入り）を記録する —
「Vault 由来の特徴量を足して本当に良くなったか」を判定する唯一の客観的材料。
"""

from __future__ import annotations

import uuid

from sqlalchemy import text

from backend.services.db.database import get_db


async def insert_ablation(
    *, computed_at: str, quarter: str, excluded_source: str, metric_name: str, metric_delta: float, sample_n: int
) -> None:
    """1 指標分のアブレーション結果を追加する（`ablation_id` は都度新規、履歴は蓄積のみ）."""
    async with get_db() as db:
        await db.execute(
            text("""
                INSERT INTO source_ablations (
                    ablation_id, computed_at, quarter, excluded_source, metric_name, metric_delta, sample_n
                ) VALUES (
                    :ablation_id, :computed_at, :quarter, :excluded_source, :metric_name, :metric_delta, :sample_n
                )
                """),
            {
                "ablation_id": str(uuid.uuid4()),
                "computed_at": computed_at,
                "quarter": quarter,
                "excluded_source": excluded_source,
                "metric_name": metric_name,
                "metric_delta": metric_delta,
                "sample_n": sample_n,
            },
        )


async def list_ablations(*, quarter: str | None = None, excluded_source: str | None = None) -> list[dict[str, object]]:
    """記録済みアブレーション結果を新しい順で返す（モデルラボ UI 表示・回帰確認用）."""
    clauses: list[str] = []
    params: dict[str, object] = {}
    if quarter is not None:
        clauses.append("quarter = :quarter")
        params["quarter"] = quarter
    if excluded_source is not None:
        clauses.append("excluded_source = :excluded_source")
        params["excluded_source"] = excluded_source
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    async with get_db() as db:
        result = await db.execute(
            text(
                f"SELECT * FROM source_ablations {where} ORDER BY computed_at DESC"  # noqa: S608  # nosec B608 - where は定数リテラルのみ・値は全てバインド
            ),
            params,
        )
        return [dict(r._mapping) for r in result]
