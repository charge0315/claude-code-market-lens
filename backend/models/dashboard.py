"""ダッシュボード（市況 / 企業ランキング / 年間値上がり率 TOP10）のレスポンスモデル.

Market Lens `backend/models/dashboard.py` から移植（変更なし）。
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel


class RankingEntry(BaseModel, frozen=True):
    """値上がり / 値下がり / 出来高ランキングの 1 銘柄分."""

    code: str
    name: str
    close: float
    change_percent: float
    volume: int


class MarketBreadth(BaseModel, frozen=True):
    """値上がり / 値下がり / 変わらず銘柄数の集計と地合いコメント."""

    advancers: int
    decliners: int
    unchanged: int
    comment: str


class RankingsResponse(BaseModel, frozen=True):
    """企業ランキング."""

    as_of_date: str
    market_breadth: MarketBreadth
    gainers: list[RankingEntry]
    losers: list[RankingEntry]
    volume_leaders: list[RankingEntry]


class YearlyPerformanceEntry(BaseModel, frozen=True):
    """年間値上がり率ランキングの 1 銘柄分."""

    code: str
    name: str
    yearly_return: float
    start_price: float
    end_price: float


class YearlyPerformanceResponse(BaseModel, frozen=True):
    """年間値上がり率 TOP10.

    `universe` は「全銘柄一括取得」で計算できたか（"all"）、フォールバック計算になったか
    （"sampled"）を正直に返す。
    """

    as_of_date: str
    base_date: str
    universe: Literal["all", "sampled"]
    universe_size: int
    top: list[YearlyPerformanceEntry]
