"""ピック当日「前日まで」の株価系列取得（🆕 Vaultアーカイブレポート用）.

`services/data/quote_service.fetch_quote_with_spark` はレポート生成時点（「今」）までの
ライブ値を返すため、レポート生成が当日より後になった場合にピック後の値動きまで
チャートへ混入してしまう（未来リーク）。ここでは `before_date`（ピック日）より前の
終値だけに明示的に絞り込み、「AIがそのピックを行った時点で見えていたはずのチャート」を
再現する。
"""

from __future__ import annotations

import asyncio
from datetime import date, datetime

from backend.services.data.data_fetcher import fetch_stock_data
from backend.services.jst_time import JST

_LOOKBACK_PERIOD = "6mo"
_MAX_POINTS = 60


def _parse_before_date(before_date: str) -> date:
    return datetime.fromisoformat(before_date[:10]).date()


async def fetch_price_history_before(symbol: str, before_date: str) -> list[tuple[str, float]]:
    """`before_date`（YYYY-MM-DD、ピック当日の日付）より前の終値系列を古い順で返す.

    取得失敗時は空リスト（フェイルソフト、呼び出し元はチャート無しで続行する）。
    """
    cutoff = _parse_before_date(before_date)
    try:
        hist = await asyncio.to_thread(fetch_stock_data, symbol, period=_LOOKBACK_PERIOD, interval="1d")
    except Exception:  # noqa: BLE001 — レポート生成を止めないフェイルソフト
        return []

    if hist.empty or "Close" not in hist.columns:
        return []

    closes = hist["Close"].dropna()
    points: list[tuple[str, float]] = []
    for idx, value in closes.items():
        idx_date = idx.tz_convert(JST).date() if idx.tzinfo is not None else idx.date()
        if idx_date >= cutoff:
            continue
        points.append((idx_date.isoformat(), float(value)))
    return points[-_MAX_POINTS:]
