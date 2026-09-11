"""株価 OHLC API（銘柄詳細画面のチャート用、🆕 P8c）.

`services/data/data_fetcher.fetch_stock_data`（既存、yfinance キャッシュ・リトライ・
ブレーカ込み）を薄くラップするだけで新規のデータ取得ロジックは持たない。複数時間軸
（分足等）は対象外 — 日足のみで期間（1mo〜2y）を切り替える設計にした。銘柄詳細の主目的は
AI 思考トレースであり（CLAUDE.md の主要画面定義でも「銘柄詳細（AI 思考トレース）」と
位置づけている）、チャートはその補助情報という位置づけのため。
"""

from __future__ import annotations

import asyncio
from typing import Literal

from fastapi import APIRouter, Query

from backend.models.common import ApiResponse
from backend.models.stock import OhlcBar
from backend.services.data.data_fetcher import fetch_stock_data

router = APIRouter(prefix="/api/stock", tags=["stock"])

_Period = Literal["1mo", "3mo", "6mo", "1y", "2y"]


@router.get("/{symbol}/ohlc", response_model=ApiResponse[list[OhlcBar]], summary="日足 OHLC 取得")
async def get_ohlc(symbol: str, period: _Period = Query(default="6mo")) -> ApiResponse[list[OhlcBar]]:
    """指定銘柄の日足 OHLC を返す（チャート表示用、取得できなければ空配列）."""
    df = await asyncio.to_thread(fetch_stock_data, symbol, period, "1d")
    if df.empty:
        return ApiResponse.ok([])
    bars = [
        OhlcBar(
            time=idx.strftime("%Y-%m-%d"),
            open=round(float(row["Open"]), 2),
            high=round(float(row["High"]), 2),
            low=round(float(row["Low"]), 2),
            close=round(float(row["Close"]), 2),
            volume=float(row["Volume"]),
        )
        for idx, row in df.iterrows()
    ]
    return ApiResponse.ok(bars)
