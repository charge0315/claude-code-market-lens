"""Gemini（challenger LLM）判定の一覧表示用サービス（🆕 P25）.

`shadow_predictions`（Anthropic公式パイプラインと並行してGeminiに同じ候補を判定させた
結果、`services/inference/orchestrator.py` 参照）を、`prediction_ledger.list_picks` と
同じ見た目（企業名・ライブ現在値・スパークライン付き）で単独一覧表示するための層。

あくまで比較表示用であり、昇格判定・確度較正には一切関与しない（CLAUDE.md）。
"""

from __future__ import annotations

import asyncio

from backend.models.pick import GeminiPickSummary
from backend.services.data.data_fetcher import _get_ticker_master
from backend.services.data.quote_service import compute_change_pct, fetch_quote_with_spark
from backend.services.db.shadow_prediction_db import list_shadow_predictions


def _f(value: object) -> float:
    return float(value) if isinstance(value, (int, float)) else 0.0


def _row_to_summary(
    row: dict[str, object],
    *,
    company_name: str | None,
    current_price: float | None,
    change_pct: float | None,
    spark: list[float] | None,
) -> GeminiPickSummary:
    payload = row["payload"] if isinstance(row["payload"], dict) else {}
    risk_factors = payload.get("risk_factors")
    holding_period = payload.get("holding_period_days")
    return GeminiPickSummary(
        shadow_id=str(row["shadow_id"]),
        pick_id=str(row["pick_id"]) if row.get("pick_id") else None,
        challenger_version=str(row["challenger_version"]),
        issued_at=str(row["issued_at"]),
        horizon_type=row["horizon_type"],
        symbol=str(row["symbol"]),
        company_name=company_name,
        direction=row["direction"],
        entry=_f(row["entry"]),
        stop=_f(row["stop"]),
        target=_f(row["target"]),
        confidence=_f(row["confidence"]),
        reasoning=str(payload["reasoning"]) if payload.get("reasoning") else None,
        risk_factors=[str(r) for r in risk_factors] if isinstance(risk_factors, list) else [],
        holding_period_days=int(holding_period) if isinstance(holding_period, (int, float)) else None,
        current_price=current_price,
        change_pct=change_pct,
        spark=spark or [],
    )


async def list_gemini_picks(
    *,
    horizon_type: str | None = None,
    issued_from: str | None = None,
    issued_to: str | None = None,
    limit: int = 50,
) -> list[GeminiPickSummary]:
    """Gemini 判定を新しい順で返す（企業名・ライブ現在値・スパークライン付き）."""
    rows = await list_shadow_predictions(
        horizon_type=horizon_type, issued_from=issued_from, issued_to=issued_to, limit=limit
    )
    if not rows:
        return []

    name_by_code = {t.code: t.name for t in await _get_ticker_master()}
    symbols = {str(row["symbol"]) for row in rows}
    quotes = dict(zip(symbols, await asyncio.gather(*[fetch_quote_with_spark(s) for s in symbols]), strict=True))

    summaries: list[GeminiPickSummary] = []
    for row in rows:
        current, prev, spark = quotes[str(row["symbol"])]
        summaries.append(
            _row_to_summary(
                row,
                company_name=name_by_code.get(str(row["symbol"])),
                current_price=current,
                change_pct=compute_change_pct(current, prev),
                spark=spark,
            )
        )
    return summaries
