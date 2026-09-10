"""業種別トレンド（週次リターン集計）のレスポンスモデル.

Market Lens `backend/models/trend.py` から移植（変更なし）。LLM でテーマ構造化する
Trend Tracking Agent（`services/data/trend/`）とは別で、これは J-Quants 日足からの
純粋な業種別週次リターン集計の型。
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel


class StockTrend(BaseModel, frozen=True):
    """業種内の 1 銘柄の週次トレンド."""

    code: str
    name: str
    weekly_return: float
    current_price: float
    week_ago_price: float


class SectorTrend(BaseModel, frozen=True):
    """1 業種の週次トレンド集計."""

    sector_code: str
    sector_name: str
    direction: Literal["up", "down", "neutral"]
    avg_weekly_return: float
    breadth: float
    stock_count: int
    top_stocks: list[StockTrend]
    reasoning: str


class TrendCatchupResponse(BaseModel, frozen=True):
    """業種別トレンドキャッチアップの全体レスポンス."""

    as_of_date: str
    uptrend_sectors: list[SectorTrend]
    downtrend_sectors: list[SectorTrend]
