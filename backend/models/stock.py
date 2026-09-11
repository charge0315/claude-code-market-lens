"""株価 OHLC のスキーマ定義（銘柄詳細画面のチャート用、🆕 P8c）."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class OhlcBar(BaseModel):
    """日足 1 本分（`lightweight-charts` のローソク足フォーマットに合わせる）."""

    model_config = ConfigDict(frozen=True)

    time: str  # YYYY-MM-DD
    open: float
    high: float
    low: float
    close: float
    volume: float
