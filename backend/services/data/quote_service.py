"""単一銘柄の現在値・前日終値を取得する共有ユーティリティ（🆕 P13）.

`services/portfolio/portfolio_service._fetch_current_price` に元々あった価格取得ロジック
（yfinance 経由、TTL キャッシュ付き `fetch_stock_data` を使用）を切り出したもの。ピック一覧
（`prediction_ledger.list_picks`）の「現在値/前日比」表示にも同じロジックを再利用するための
共有化 — DRY。企業名/セクター等の付随情報は呼び出し元（`portfolio_service`）側に残す。
"""

from __future__ import annotations

import asyncio
import logging

from backend.services.data.data_fetcher import fetch_stock_data

logger = logging.getLogger(__name__)


async def fetch_quote(symbol: str) -> tuple[float | None, float | None]:
    """直近の終値・前日終値を返す（表示専用のライブ値、DB へは永続化しない）.

    Returns
    -------
    tuple of (current_price, prev_close)。取得失敗時は (None, None)（フェイルソフト）。
    """
    try:
        hist = await asyncio.to_thread(fetch_stock_data, symbol, period="5d", interval="1d")
    except Exception:  # noqa: BLE001 — 表示専用のライブ値取得。失敗しても呼び出し元は継続する
        logger.warning("現在値の取得に失敗しました（%s）", symbol, exc_info=True)
        return None, None

    if hist.empty or "Close" not in hist.columns:
        return None, None
    closes = hist["Close"].dropna()
    current = float(closes.iloc[-1]) if len(closes) >= 1 else None
    prev = float(closes.iloc[-2]) if len(closes) >= 2 else None
    return current, prev
