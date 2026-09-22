"""株価 OHLC API（銘柄詳細・チャート画面用、🆕 P8c）.

`services/data/data_fetcher.fetch_stock_data`（既存、yfinance キャッシュ・リトライ・
ブレーカ込み）を薄くラップするだけで新規のデータ取得ロジックは持たない。日足に加え、
🆕 分足（60分足/15分足）にも対応する（`/chart` 画面向け、任意銘柄を素早く見る用途では
より細かい粒度が欲しいというユーザー要望）。銘柄詳細画面は AI 思考トレースが主目的で
チャートは補助情報という位置づけ（CLAUDE.md）のため日足のみのまま据え置き、フロント側
（`PriceChart` の `enableIntervalSelector`）で足種選択 UI を `/chart` 画面に限定する。
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
from backend.services.jst_time import JST, to_jst
from backend.services.scoring.technical_analysis import detect_cross_events
from backend.services.vault.brand_notes_service import get_raw_note_content

router = APIRouter(prefix="/api/stock", tags=["stock"])

_Period = Literal["1mo", "3mo", "6mo", "1y", "2y"]
_Interval = Literal["1d", "60m", "15m"]

# 🆕 分足の取得可能期間。Yahoo Finance（yfinance）の実測上の上限は 60分足=730日・15分足=60日
# だが境界値ぎりぎりは失敗しうるため安全マージンを持たせて制限する。要求期間がここに無ければ
# 直近の許容値（タプル末尾）へ丸める（`_INTRADAY_ALLOWED_PERIODS[interval][-1]`）。
_INTRADAY_ALLOWED_PERIODS: Final[dict[_Interval, tuple[_Period, ...]]] = {
    "60m": ("1mo", "3mo", "6mo", "1y"),
    "15m": ("1mo",),
}

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


@router.get(
    "/{symbol}/ohlc",
    response_model=ApiResponse[OhlcResponse],
    summary="OHLC 取得（日足は兆候イベント込み、🆕 分足対応）",
)
async def get_ohlc(
    symbol: str, period: _Period = Query(default="6mo"), interval: _Interval = Query(default="1d")
) -> ApiResponse[OhlcResponse]:
    """指定銘柄の OHLC を返す（チャート表示用）.

    日足（既定）はゴールデンクロス/デッドクロス等の兆候イベントも計算して返す。🆕 分足
    （60分足/15分足）は `_intraday_ohlc` へ委譲し、`events` は常に空で返す — GC/DC・MACD
    クロスは日付（YYYY-MM-DD）単位で検出するため、同日内に複数本並ぶ分足では日付キーが
    重複しマーカーの突き合わせが破綻する。分足に対応した兆候検出は将来必要になれば別途
    設計する。
    """
    if interval != "1d":
        return await _intraday_ohlc(symbol, period, interval)

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


async def _intraday_ohlc(symbol: str, period: _Period, interval: _Interval) -> ApiResponse[OhlcResponse]:
    """分足 OHLC を返す（🆕、`/chart` 画面の足種選択用）.

    `period` が対応する `_INTRADAY_ALLOWED_PERIODS[interval]` の範囲外なら、yfinance の
    取得上限を超えないよう直近の許容値へ丸める（フロント側は許容期間のボタンしか出さない
    想定だが、API 単体で叩かれた場合の防御でもある）。
    """
    allowed = _INTRADAY_ALLOWED_PERIODS[interval]
    effective_period = period if period in allowed else allowed[-1]
    df = await asyncio.to_thread(fetch_stock_data, symbol, effective_period, interval)
    if df.empty:
        return ApiResponse.ok(OhlcResponse(bars=[], events=[]))

    bars = [
        OhlcBar(
            time=int(to_jst(idx).timestamp()),
            open=round(float(row["Open"]), 2),
            high=round(float(row["High"]), 2),
            low=round(float(row["Low"]), 2),
            close=round(float(row["Close"]), 2),
            volume=float(row["Volume"]),
        )
        for idx, row in df.iterrows()
    ]
    return ApiResponse.ok(OhlcResponse(bars=bars, events=[]))


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
