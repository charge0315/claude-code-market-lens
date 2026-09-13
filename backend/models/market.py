"""市況スナップショット（指数ティッカー行）のスキーマ（🆕 P13）.

ダッシュボード上部の指数ティッカー行（日経平均・TOPIX・グロース250・S&P500・USD/JPY・
日経VI）用。表示専用のライブ値であり、`prediction_ledger` 等へは一切永続化しない。
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict

MarketStatus = Literal["寄り前", "ザラ場中", "引け後"]


class IndexQuote(BaseModel):
    """1 指数分の現在値・前日比."""

    model_config = ConfigDict(frozen=True)

    label: str
    value: float
    change: float
    change_pct: float
    # 🆕 P23: 直近の終値系列（簡易スパークライン表示用、表示専用・DB非永続）。
    spark: list[float] = []


class MarketSnapshot(BaseModel):
    """`GET /api/market/snapshot` の応答."""

    model_config = ConfigDict(frozen=True)

    indices: list[IndexQuote]
    market_status: MarketStatus
    updated_at: str
