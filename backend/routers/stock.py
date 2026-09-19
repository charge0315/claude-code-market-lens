"""株価 OHLC API（銘柄詳細画面のチャート用、🆕 P8c）.

`services/data/data_fetcher.fetch_stock_data`（既存、yfinance キャッシュ・リトライ・
ブレーカ込み）を薄くラップするだけで新規のデータ取得ロジックは持たない。複数時間軸
（分足等）は対象外 — 日足のみで期間（1mo〜2y）を切り替える設計にした。銘柄詳細の主目的は
AI 思考トレースであり（CLAUDE.md の主要画面定義でも「銘柄詳細（AI 思考トレース）」と
位置づけている）、チャートはその補助情報という位置づけのため。
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
from typing import Final, Literal

from fastapi import APIRouter, Query
from pydantic import BaseModel

from backend.models.common import ApiResponse
from backend.models.stock import ChartEvent, OhlcBar, OhlcResponse, Quote
from backend.models.stocks import TickerInfo
from backend.services.data.data_fetcher import fetch_stock_data, search_tickers
from backend.services.data.quote_service import fetch_quote
from backend.services.jst_time import JST
from backend.services.scoring.technical_analysis import detect_cross_events
from backend.services.vault.brand_notes_service import get_raw_note_content

router = APIRouter(prefix="/api/stock", tags=["stock"])

_Period = Literal["1mo", "3mo", "6mo", "1y", "2y"]

# SMA25・MACD の計算には表示期間より前のデータが必要（先頭付近が NaN のまま返らないよう、
# 表示期間より長い期間を取得してから計算し、最後に元の期間へ切り詰める、🆕）。
_EXTENDED_PERIOD_FOR: Final[dict[_Period, str]] = {
    "1mo": "3mo",
    "3mo": "6mo",
    "6mo": "1y",
    "1y": "2y",
    "2y": "5y",
}

# yfinance の period はカレンダー日数基準のため、切り詰めも同じ基準で行う（概算値、閏年等の
# 誤差は許容 — 1〜2日のズレが生じても表示上問題にならない）。
_PERIOD_CALENDAR_DAYS: Final[dict[_Period, int]] = {
    "1mo": 31,
    "3mo": 92,
    "6mo": 183,
    "1y": 366,
    "2y": 731,
}


@router.get("/search", response_model=ApiResponse[list[TickerInfo]], summary="銘柄検索（証券コード/銘柄名の部分一致）")
async def search(q: str = Query(default="", min_length=0)) -> ApiResponse[list[TickerInfo]]:
    """証券コードまたは銘柄名の部分一致で銘柄マスタを検索する（🆕 P26、ポートフォリオへの銘柄追加用）."""
    return ApiResponse.ok(await search_tickers(q))


class StockNote(BaseModel):
    """`GET /api/stock/{symbol}/note` のレスポンス（UI 表示専用、本文込み）."""

    code: str
    note_title: str
    content: str


@router.get("/{symbol}/quote", response_model=ApiResponse[Quote], summary="直近値取得（取引フォームの初期値用）")
async def get_quote(symbol: str) -> ApiResponse[Quote]:
    """指定銘柄の直近値を返す（ポートフォリオの買い/売りフォームが開いた時点の最新値を
    初期値として提示するために使う。取得失敗時も price=null で返し、呼び出し元が
    手入力にフォールバックできるようにする）."""
    current, prev = await fetch_quote(symbol)
    change_pct = (current - prev) / prev * 100 if current is not None and prev is not None and prev != 0 else None
    return ApiResponse.ok(Quote(symbol=symbol, price=current, prev_close=prev, change_pct=change_pct))


@router.get("/{symbol}/ohlc", response_model=ApiResponse[OhlcResponse], summary="日足 OHLC 取得（兆候イベント込み）")
async def get_ohlc(symbol: str, period: _Period = Query(default="6mo")) -> ApiResponse[OhlcResponse]:
    """指定銘柄の日足 OHLC と、ゴールデンクロス/デッドクロス等の兆候イベントを返す（チャート表示用）.

    🆕 SMA25・MACD の計算精度を確保するため、実際には表示期間より長い期間
    （`_EXTENDED_PERIOD_FOR`）を取得してから `events` を計算し、`bars` は元の表示期間へ
    切り詰めて返す（先頭付近の指標が NaN のまま交差判定を誤らないようにするため）。
    """
    extended_period = _EXTENDED_PERIOD_FOR[period]
    df = await asyncio.to_thread(fetch_stock_data, symbol, extended_period, "1d")
    if df.empty:
        return ApiResponse.ok(OhlcResponse(bars=[], events=[]))

    events = [ChartEvent(**e) for e in detect_cross_events(df)]

    cutoff = (datetime.now(JST) - timedelta(days=_PERIOD_CALENDAR_DAYS[period])).date()
    display = df[df.index.date >= cutoff]
    bars = [
        OhlcBar(
            time=idx.strftime("%Y-%m-%d"),
            open=round(float(row["Open"]), 2),
            high=round(float(row["High"]), 2),
            low=round(float(row["Low"]), 2),
            close=round(float(row["Close"]), 2),
            volume=float(row["Volume"]),
        )
        for idx, row in display.iterrows()
    ]
    cutoff_str = cutoff.isoformat()
    return ApiResponse.ok(OhlcResponse(bars=bars, events=[e for e in events if e.date >= cutoff_str]))


@router.get(
    "/{symbol}/note",
    response_model=ApiResponse[StockNote | None],
    summary="銘柄ナレッジノート（本文込み、UI 表示専用）",
)
async def get_note(symbol: str) -> ApiResponse[StockNote | None]:
    """指定銘柄の Vault ノートを本文込みで返す（ユーザー本人への画面表示専用。LLM へは渡さない）.

    ノート未整備・読み込み失敗時は `data=null` を返す（エラー扱いにしない — 多くの銘柄は
    ノートが未作成のため正常系として扱う）。
    """
    result = await get_raw_note_content(symbol)
    if result is None:
        return ApiResponse.ok(None)
    note_title, content = result
    return ApiResponse.ok(StockNote(code=symbol, note_title=note_title, content=content))
