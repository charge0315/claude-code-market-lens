"""大引け後レビュー（EOD Review）の Pydantic スキーマ定義.

Market Lens `models/ai_portfolio_eod.py` から構造のみ参考にした（🆕）。Market Lens 版は
`reconciliation`（定量突合）/ `intervention_analysis`（介入分析）を専用カラムへ永続化するが、
Alpha Forge の `eod_reviews` テーブルは `summary` / `learned_heuristics` のみ（baseline
スキーマ、P1）。定量集計（`portfolio_signals` の承認/却下/実約定件数）は生成時にプロンプトへ
埋め込むだけの中間値として扱い、永続化・API 応答には含めない設計にした。
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class HeuristicItem(BaseModel):
    """学習した教訓 1 件."""

    model_config = ConfigDict(frozen=True)

    heuristic: str
    evidence: str
    confidence: float  # 0.0-1.0


class EodReview(BaseModel):
    """大引け後レビュー 1 日分（`eod_reviews` テーブルに対応、`review_date` で 1 日 1 件）."""

    model_config = ConfigDict(frozen=True)

    review_date: str
    created_at: str
    summary: str
    learned_heuristics: list[HeuristicItem]
