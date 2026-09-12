"""ダッシュボード指数ティッカー行のスナップショット取得（🆕 P13）.

`fetch_macro_symbol_data`（yfinance、TTL キャッシュ付き、`macro_features.py` と同じ関数）で
主要指数を並列取得する。日経VI は yfinance 制約で CBOE VIX（`^VIX`）を代替使用（CLAUDE.md /
`macro_features.py` と同じ踏襲）。個々の指数が取得できない場合は結果から除外し（フェイル
ソフト）、一部欠けても残りの指数だけで画面を成立させる（全指数が必ず揃う前提を置かない）。
"""

from __future__ import annotations

import asyncio
import logging

from backend.models.market import IndexQuote
from backend.services.data.data_fetcher import fetch_macro_symbol_data

logger = logging.getLogger(__name__)

# (yfinance シンボル, 表示ラベル)。TOPIX/グロース250/S&P500 は Alpha Forge 初導入のため、
# 実運用で解決できない場合は自動的にスキップされる（フェイルソフト、固定登録のみ）。
_INDEX_SYMBOLS: tuple[tuple[str, str], ...] = (
    ("^N225", "日経平均株価"),
    ("^TPX", "TOPIX"),
    ("^GSPC", "S&P 500"),
    ("JPY=X", "USD/JPY"),
    ("^VIX", "日経VI"),
)


async def _fetch_one(symbol: str, label: str) -> IndexQuote | None:
    try:
        hist = await asyncio.to_thread(fetch_macro_symbol_data, symbol, "5d", "1d")
    except Exception:  # noqa: BLE001 — 1 指数の失敗で他指数まで巻き込まない
        logger.warning("指数データの取得に失敗しました（%s）", symbol, exc_info=True)
        return None

    if hist.empty or "Close" not in hist.columns:
        return None
    closes = hist["Close"].dropna()
    if len(closes) < 2:
        return None
    current = float(closes.iloc[-1])
    prev = float(closes.iloc[-2])
    change = current - prev
    change_pct = (change / prev * 100.0) if prev != 0 else 0.0
    return IndexQuote(label=label, value=current, change=change, change_pct=change_pct)


async def get_market_snapshot() -> list[IndexQuote]:
    """固定の指数リストを並列取得し、取得できたものだけを返す（フェイルソフト）."""
    results = await asyncio.gather(*[_fetch_one(symbol, label) for symbol, label in _INDEX_SYMBOLS])
    return [r for r in results if r is not None]
