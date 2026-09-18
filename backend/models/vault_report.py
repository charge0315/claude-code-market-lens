"""Vaultアーカイブレポートのスキーマ（🆕）.

本日のAIピックの根拠・4分析内訳・チャート（ピック前日まで）・市況ニュースを1つのHTMLに
まとめ、Obsidian Vaultの `Daily/AlphaForge/<日付>/` へ保存する（個人用アーカイブ、
Market Lens の `Daily/YYYY-MM-DD.md` とは別パスで自己参照ループを避ける）。
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class VaultReportResult(BaseModel):
    """レポート生成結果（保存先パスと件数のみ。本文はVault側のファイルを直接参照する）."""

    model_config = ConfigDict(frozen=True)

    report_date: str
    report_dir: str
    mid_term_count: int
    short_term_count: int
    chart_count: int


class PipelineLogResult(BaseModel):
    """日次パイプラインログ生成結果（🆕 P30、保存先パスと件数のみ）."""

    model_config = ConfigDict(frozen=True)

    log_date: str
    log_path: str
    candidate_count: int
    shortlisted_count: int
    ledger_count: int
    resolved_outcome_count: int
    eval_metric_count: int
    promotion_count: int
    champion_swap_count: int
