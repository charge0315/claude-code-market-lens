"""株価 OHLC のスキーマ定義（銘柄詳細画面のチャート用、🆕 P8c）."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict


class OhlcBar(BaseModel):
    """ローソク足 1 本分（`lightweight-charts` のフォーマットに合わせる）.

    `time` は日足（interval="1d"）では `YYYY-MM-DD` 文字列、分足（🆕、interval="60m"/"15m"）
    では UTC 起点の Unix 秒（`int`）。`lightweight-charts` の `Time` 型が「日付文字列は
    1日単位の解像度までしか表現できない」制約を持つため、同日内に複数本並ぶ分足はタイム
    スタンプで表現する必要がある（`routers/stock.py` 参照）。
    """

    model_config = ConfigDict(frozen=True)

    time: str | int
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


class IndicatorLine(BaseModel):
    """オーバーレイ/サブインジケーターの1系列上の1点（🆕 P34）.

    `time` は `OhlcBar.time` と同じ規約（日足=`YYYY-MM-DD`文字列、分足=Unix秒）。
    一目均衡表の先行スパンのみ、元の `bars` に無い未来日付が末尾に追加で含まれる
    （`technical_analysis.calculate_ichimoku` 参照）。
    """

    model_config = ConfigDict(frozen=True)

    time: str | int
    value: float | None


OverlayKind = Literal["sma", "ichimoku", "bollinger"]
SubIndicatorKind = Literal["macd", "rsi", "stochastics"]


class OverlaySeries(BaseModel):
    """価格チャートに重ねて表示するオーバーレイ指標（🆕 P34、`/chart` 画面の足種セレクタ同様
    日足専用 — 分足は `routers/stock.py` の日付キー衝突制約により対象外）."""

    model_config = ConfigDict(frozen=True)

    kind: OverlayKind
    lines: dict[str, list[IndicatorLine]]


class SubIndicatorSeries(BaseModel):
    """価格チャート下段の別ペインに表示するサブインジケーター（🆕 P34、日足専用）.

    出来高は `bars[].volume` から直接描画できるためここには含めない
    （フロントエンド `PriceChart.tsx` 参照）。
    """

    model_config = ConfigDict(frozen=True)

    kind: SubIndicatorKind
    lines: dict[str, list[IndicatorLine]]


class OhlcResponse(BaseModel):
    """`GET /api/stock/{symbol}/ohlc` のレスポンス（🆕、四本値＋兆候イベント＋指標）."""

    model_config = ConfigDict(frozen=True)

    bars: list[OhlcBar]
    events: list[ChartEvent]
    overlay: OverlaySeries | None = None
    sub_indicator: SubIndicatorSeries | None = None


class Quote(BaseModel):
    """単一銘柄の直近値（🆕 P26、ポートフォリオの買い/売りフォームで取引時点の最新値を
    初期値に使うための軽量エンドポイント用）."""

    model_config = ConfigDict(frozen=True)

    symbol: str
    price: float | None
    prev_close: float | None
    change_pct: float | None
