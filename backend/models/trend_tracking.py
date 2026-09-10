"""Trend Tracking Agent の構造化トレンド（トレンドオントロジー）モデル.

Market Lens `backend/models/trend_tracking.py` から移植（変更なし）。外部トピック
（ニュース見出し・セクター騰落等）を LLM で構造化した「トレンド」を、ピックパイプラインへ
定量データとして渡す共通スキーマ（`plans/01_PRD` §5.5）。
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

LifecycleStage = Literal["EMERGING", "EXPANDING", "PEAK", "DECLINING"]
ImpactHorizon = Literal["SHORT", "MID", "LONG"]
SnapshotStatus = Literal["ok", "mock", "not_configured", "llm_error", "no_signals"]


class RelatedTicker(BaseModel):
    """トレンドに関連する銘柄と、その関連づけの根拠."""

    model_config = ConfigDict(frozen=True)

    ticker: str
    name: str
    correlation_rationale: str


class Trend(BaseModel):
    """1 つの構造化トレンド（トレンドオントロジーの 1 要素）.

    sentiment_score は -1.0（極めて弱気）〜 +1.0（極めて強気）、
    momentum_score は 0〜100（話題の急上昇度）。
    """

    model_config = ConfigDict(frozen=True)

    trend_id: str
    timestamp: str
    theme_name: str
    summary: str
    lifecycle_stage: LifecycleStage
    sentiment_score: float = Field(ge=-1.0, le=1.0)
    momentum_score: float = Field(ge=0.0, le=100.0)
    impact_horizon: ImpactHorizon
    related_tickers: list[RelatedTicker] = []
    keywords: list[str] = []


class TrendSnapshot(BaseModel):
    """ある時点で収集・分析したトレンド一覧のスナップショット（1 行 = 1 スナップショット）."""

    model_config = ConfigDict(frozen=True)

    snapshot_at: str
    status: SnapshotStatus
    model: str
    trends: list[Trend] = []
    signal_count: int = 0
    source_summary: str = ""
    generated_at: str
    message: str | None = None
