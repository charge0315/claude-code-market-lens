"""株価 OHLC のスキーマ定義（銘柄詳細画面のチャート用、🆕 P8c）."""

from __future__ import annotations

from typing import Literal

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


class ChartEvent(BaseModel):
    """テクニカル指標のクロスイベント 1 件（🆕、ローソク足チャートのマーカー表示用）.

    `services/scoring/technical_analysis.detect_cross_events` の結果をそのまま公開する。
    """

    model_config = ConfigDict(frozen=True)

    date: str  # YYYY-MM-DD
    kind: Literal["golden_cross", "dead_cross", "macd_bullish_cross", "macd_bearish_cross"]
    label: str


class OhlcResponse(BaseModel):
    """`GET /api/stock/{symbol}/ohlc` のレスポンス（🆕、四本値＋兆候イベント）."""

    model_config = ConfigDict(frozen=True)

    bars: list[OhlcBar]
    events: list[ChartEvent]


class Quote(BaseModel):
    """単一銘柄の直近値（🆕 P26、ポートフォリオの買い/売りフォームで取引時点の最新値を
    初期値に使うための軽量エンドポイント用）."""

    model_config = ConfigDict(frozen=True)

    symbol: str
    price: float | None
    prev_close: float | None
    change_pct: float | None
