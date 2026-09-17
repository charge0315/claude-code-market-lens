"""LLM プロバイダ共通層の型定義."""

from __future__ import annotations

from typing import Literal

JsonDict = dict[str, object]

ProviderId = Literal["anthropic", "openai", "gemini"]
# note_publish（🆕 日次noteドラフト生成）は公式/シャドウ設定UIには出さない（比較表示の
# 対象ではなく、シャドウ生成しても使い道が無いため、YAGNI）。モデル解決・api_cost 記録のためだけに
# 機能IDとして登録する（`services/llm/registry.py`）。
FeatureId = Literal["stock_pick", "portfolio_signal", "eod_review", "trend_analyzer", "note_publish"]

PROVIDER_IDS: tuple[ProviderId, ...] = ("anthropic", "openai", "gemini")
FEATURE_IDS: tuple[FeatureId, ...] = (
    "stock_pick",
    "portfolio_signal",
    "eod_review",
    "trend_analyzer",
    "note_publish",
)
