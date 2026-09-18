"""機能ごとのプロバイダ選択・併用を可能にする共通プロトコル.

`AnthropicClient`/`OpenAIClient`/`GeminiClient` はいずれもこの Protocol を満たす（構造的部分型、
継承は不要）。`registry.py` はこの Protocol の型でプロバイダを扱うことで、呼び出し側
（`orchestrator.py`/`signal_service.py`/`eod_review_service.py`/`trend/analyzer.py`）が
具象クライアントに直接依存しないようにする。
"""

from __future__ import annotations

from typing import Protocol

from backend.services.llm.types import FeatureId, JsonDict


class LLMProvider(Protocol):
    """6 機能（stock_pick/portfolio_signal/eod_review/trend_analyzer/note_publish/news_sentiment）
    共通の LLM クライアント形状."""

    provider_id: str

    @property
    def is_configured(self) -> bool: ...

    def model_for(self, feature: FeatureId) -> str:
        """指定機能で実際に使うモデルID（機能×プロバイダの個別設定 or プロバイダ既定値）を返す."""
        ...

    async def propose_stock_pick(self, *, ticker: str, prompt: str) -> JsonDict: ...

    async def propose_portfolio_signal(self, *, symbol: str, prompt: str) -> JsonDict: ...

    async def propose_eod_review(self, *, prompt: str) -> JsonDict: ...

    async def propose_trends(self, *, prompt: str) -> JsonDict: ...

    async def propose_daily_note(self, *, prompt: str) -> JsonDict: ...

    async def propose_news_sentiment(self, *, ticker: str, prompt: str) -> JsonDict: ...
