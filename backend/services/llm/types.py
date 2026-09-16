"""LLM プロバイダ共通層の型定義."""

from __future__ import annotations

from typing import Literal

JsonDict = dict[str, object]

ProviderId = Literal["anthropic", "openai", "gemini"]
FeatureId = Literal["stock_pick", "portfolio_signal", "eod_review", "trend_analyzer"]

PROVIDER_IDS: tuple[ProviderId, ...] = ("anthropic", "openai", "gemini")
FEATURE_IDS: tuple[FeatureId, ...] = ("stock_pick", "portfolio_signal", "eod_review", "trend_analyzer")
