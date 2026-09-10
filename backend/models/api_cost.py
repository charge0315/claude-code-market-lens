"""API コスト台帳のレスポンスモデル.

Market Lens `backend/models/performance_ledger.py` の ApiCost 系を移植（変更なし）。
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class ApiCostDailyRow(BaseModel):
    """api_costs の 1 行（日付 × 機能の集計）."""

    model_config = ConfigDict(frozen=True)

    log_date: str
    feature: str
    call_count: int
    input_tokens: int
    output_tokens: int
    est_cost_usd: float


class ApiCostSummary(BaseModel):
    """直近 N 日の Claude API コストサマリ."""

    model_config = ConfigDict(frozen=True)

    since_date: str
    total_cost_usd: float
    total_calls: int
    by_feature: dict[str, float]
    rows: list[ApiCostDailyRow]
