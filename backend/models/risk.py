"""ポートフォリオのリスクチェック（セクター集中度・銘柄間相関）関連の Pydantic モデル定義.

Market Lens `backend/models/risk.py` から移植（🔧、`ticker_*` → `symbol_*` へ改称。
Alpha Forge の AI 銘柄ピック向けバリアント（`analyze_stock_pick_risk`）は対象外 —
Market Lens の `stock_pick_runs` JSON blob 前提で、Alpha Forge の `prediction_ledger`
とは形が異なるため移植しない）。
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class SectorConcentrationWarning(BaseModel):
    """特定セクターへ評価額が集中している警告."""

    model_config = ConfigDict(frozen=True)

    sector: str
    pct: float  # 保有評価額全体に対するこのセクターの比率（0-100）
    exceeds_threshold: bool  # 閾値（risk_service._SECTOR_CONCENTRATION_THRESHOLD_PCT）を超えているか


class CorrelationWarning(BaseModel):
    """値動きが似ている（分散効果が薄い）銘柄ペアの警告."""

    model_config = ConfigDict(frozen=True)

    symbol_a: str
    symbol_b: str
    company_name_a: str | None = None
    company_name_b: str | None = None
    correlation: float  # 直近リターン系列のピアソン相関係数（-1〜1）


class PortfolioRiskReport(BaseModel):
    """ポートフォリオのリスクチェック結果."""

    model_config = ConfigDict(frozen=True)

    analyzed_count: int  # 分析対象銘柄数
    sector_warnings: list[SectorConcentrationWarning]
    correlation_warnings: list[CorrelationWarning]
    correlation_skipped: bool  # 銘柄数不足（2銘柄未満）等で相関計算自体をスキップしたか
    message: str | None = None  # 分析対象が無い場合の補足メッセージ
    generated_at: str  # この結果を生成した ISO タイムスタンプ（JST）
