"""ポートフォリオ評価サービス.

Market Lens `backend/services/portfolio_service.py` から移植（🔧、`portfolios` テーブルの
列名差分に合わせて調整: `ticker`→`symbol`、`id`(int)→`holding_id`(str)、`added_at`→
`acquired_at`）。DB から保有銘柄（ロット単位）を読み込み、直近の終値（yfinance、TTL キャッシュ
経由）で評価損益を算出する。
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime

from backend.models.portfolio import PortfolioHolding, PortfolioSummary, SectorAllocation
from backend.services.data.data_fetcher import get_company_info
from backend.services.data.quote_service import fetch_quote
from backend.services.db.portfolio_db import list_holdings
from backend.services.jst_time import JST

logger = logging.getLogger(__name__)

_UNKNOWN_SECTOR = "その他"


def _as_int(value: object) -> int:
    return int(value) if isinstance(value, (int, float)) else 0


def _as_float(value: object) -> float:
    return float(value) if isinstance(value, (int, float)) else 0.0


async def _fetch_current_price(symbol: str) -> tuple[float | None, float | None, str | None, str | None]:
    """直近の終値・前日終値・企業名・セクターを取得する.

    価格取得は `services/data/quote_service.fetch_quote`（🔧 P13 で共有化、ピック一覧の
    現在値表示とロジックを共有）へ委譲し、企業名/セクターは `get_company_info`
    （TTL キャッシュ付き）を並列取得する。

    Returns
    -------
    tuple of (current_price, prev_close, company_name, sector)
    """
    try:
        company_info, (current, prev) = await asyncio.gather(
            asyncio.to_thread(get_company_info, symbol),
            fetch_quote(symbol),
        )
    except Exception:
        logger.exception("現在価格の取得に失敗: %s", symbol)
        return None, None, None, None

    name = company_info.get("name") if company_info else None
    sector = company_info.get("sector") if company_info else None
    return current, prev, name, sector


async def build_portfolio() -> PortfolioSummary:
    """DB の保有銘柄（ロット単位）に現在価格を付与してポートフォリオサマリーを構築する."""
    raw_holdings = await list_holdings()
    now = datetime.now(JST).isoformat(timespec="seconds")

    symbols = [str(row["symbol"]) for row in raw_holdings]
    # 銘柄ごとの価格取得を並列化する（保有銘柄数に比例した逐次ブロッキングを避ける）。
    price_results = await asyncio.gather(*[_fetch_current_price(s) for s in symbols])

    enriched: list[PortfolioHolding] = []
    sector_map: dict[str, float] = {}
    day_gain_loss_total = 0.0
    day_gain_loss_known = False

    for row, (current_price, prev_close, company_name, sector) in zip(raw_holdings, price_results, strict=True):
        symbol = str(row["symbol"])
        quantity = _as_int(row["quantity"])
        avg_cost = _as_float(row["avg_cost"])
        cost_basis = quantity * avg_cost

        current_value: float | None = None
        gain_loss: float | None = None
        return_pct: float | None = None

        if current_price is not None:
            current_value = quantity * current_price
            gain_loss = current_value - cost_basis
            return_pct = gain_loss / cost_basis if cost_basis != 0 else None

        if current_price is not None and prev_close is not None:
            day_gain_loss_total += quantity * (current_price - prev_close)
            day_gain_loss_known = True

        enriched.append(
            PortfolioHolding(
                holding_id=str(row["holding_id"]),
                symbol=symbol,
                company_name=company_name,
                sector=sector,
                quantity=quantity,
                avg_cost=avg_cost,
                current_price=current_price,
                current_value=current_value,
                cost_basis=cost_basis,
                gain_loss=gain_loss,
                return_pct=return_pct,
                acquired_at=str(row["acquired_at"]),
            )
        )

        # セクター別評価額を集計（価格不明な銘柄はコスト基準で計上）
        sector_key = sector or _UNKNOWN_SECTOR
        sector_map[sector_key] = sector_map.get(sector_key, 0.0) + (
            current_value if current_value is not None else cost_basis
        )

    total_value = sum(h.current_value if h.current_value is not None else h.cost_basis for h in enriched)
    total_cost = sum(h.cost_basis for h in enriched)
    total_gain_loss = total_value - total_cost
    total_return_pct = total_gain_loss / total_cost if total_cost != 0 else 0.0

    sector_allocations = [
        SectorAllocation(sector=s, value=v, pct=(v / total_value * 100) if total_value > 0 else 0.0)
        for s, v in sorted(sector_map.items(), key=lambda x: x[1], reverse=True)
    ]

    return PortfolioSummary(
        total_value=total_value,
        total_cost=total_cost,
        total_gain_loss=total_gain_loss,
        total_return_pct=total_return_pct,
        # 保有銘柄が1件も無い、または全銘柄で前日終値が取得できなかった場合は None
        # （「当日変動0円」と「取得できなかった」を区別する）。
        day_gain_loss=day_gain_loss_total if day_gain_loss_known else None,
        holdings=enriched,
        sector_allocations=sector_allocations,
        holding_count=len(enriched),
        updated_at=now,
    )
