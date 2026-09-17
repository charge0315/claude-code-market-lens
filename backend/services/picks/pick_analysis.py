"""ピック1件分の詳細素材（4分析スコア内訳・情報源内訳・リスク要因）を組み立てる共通ヘルパー.

`services/notes/note_generator.py`（note下書き生成）と `services/vault_report/`（Vaultアーカイブ
レポート）の両方が、entry/stop/target を含まない同じ「根拠の詳細」を必要とするため、
`PickSummary` + `prediction_ledger` の生行から `PickAnalysis` を組み立てるロジックをここへ
一本化する（DRY）。
"""

from __future__ import annotations

from dataclasses import dataclass, field

from backend.models.pick import PickSummary
from backend.services.ledger import prediction_ledger as pl


def _f(value: object) -> float:
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else 0.0


@dataclass(frozen=True)
class PickAnalysis:
    """1銘柄分の詳細な分析素材（entry/stop/target は一切含まない）."""

    symbol: str
    company_name: str | None
    direction: str
    composite_score: float
    confidence: float
    confidence_bucket: str
    concordance: float
    rationale_text: str
    reasoning_tags: list[str] = field(default_factory=list)
    sub_scores: dict[str, float] = field(default_factory=dict)
    source_contributions: dict[str, object] = field(default_factory=dict)
    llm_risk_factors: list[str] = field(default_factory=list)
    holding_period_days: int | None = None
    pick_id: str = ""


async def to_pick_analysis(summary: PickSummary) -> PickAnalysis:
    """`PickSummary`（一覧用）を、台帳の生行から4分析スコア内訳・リスク要因を補って詳細化する.

    一覧API（`prediction_ledger.list_picks`）には含まれない `sub_scores`（4分析内訳）と
    `rationale_struct`（リスク要因・想定保有期間）を追加で取得する。
    """
    raw = await pl.get_pick(summary.pick_id)
    sub_scores: dict[str, float] = {}
    llm_risk_factors: list[str] = []
    holding_period_days: int | None = None
    if raw is not None:
        sub_scores = {
            "technical": _f(raw.get("sub_score_technical")),
            "trend": _f(raw.get("sub_score_trend")),
            "fundamental": _f(raw.get("sub_score_fundamental")),
            "sentiment": _f(raw.get("sub_score_sentiment")),
        }
        rationale_struct = raw.get("rationale_struct")
        if isinstance(rationale_struct, dict):
            risks = rationale_struct.get("llm_risk_factors")
            if isinstance(risks, list):
                llm_risk_factors = [str(r) for r in risks]
            holding = rationale_struct.get("holding_period_days")
            if isinstance(holding, (int, float)):
                holding_period_days = int(holding)

    return PickAnalysis(
        symbol=summary.symbol,
        company_name=summary.company_name,
        direction=summary.direction,
        composite_score=summary.composite_score,
        confidence=summary.confidence,
        confidence_bucket=summary.confidence_bucket,
        concordance=summary.concordance,
        rationale_text=summary.rationale_text,
        reasoning_tags=summary.reasoning_tags,
        sub_scores=sub_scores,
        source_contributions=summary.source_contributions,
        llm_risk_factors=llm_risk_factors,
        holding_period_days=holding_period_days,
        pick_id=summary.pick_id,
    )
