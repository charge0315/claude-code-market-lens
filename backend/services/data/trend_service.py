"""過去 1 週間の株価トレンドを業種別に集計するサービス.

Market Lens `backend/services/trend_service.py` から移植（import パスのみ変更）。
J-Quants の銘柄マスタで業種分類を取得し、各銘柄の週次リターンから上昇 / 下降トレンドの
業種をピックアップする（LLM は使わない純粋な定量集計。LLM でテーマ構造化する Trend
Tracking Agent は `services/data/trend/`（P3 で移植））。
"""

from __future__ import annotations

import asyncio
import datetime
import logging
import time
from typing import TypedDict

from backend.models.trend import SectorTrend, StockTrend, TrendCatchupResponse
from backend.services.data.jquants_client import JsonDict, jquants
from backend.services.data.jquants_errors import JQuantsError

logger = logging.getLogger(__name__)


class _SectorInfo(TypedDict):
    code: str
    stocks: list[JsonDict]


class _PriceResult(TypedDict):
    name: str
    sector: str
    weekly_return: float
    current: float
    week_ago: float


# 業種ごとに抽出する銘柄数の上限（API 呼び出し数を抑制）。
_MAX_STOCKS_PER_SECTOR = 5
# 同時リクエスト数の上限（J-Quants レートリミット対策）。
_CONCURRENCY = 10

_cache: dict[str, tuple[float, TrendCatchupResponse]] = {}
_CACHE_TTL_SEC = 3600
_lock = asyncio.Lock()


async def get_trend_catchup() -> TrendCatchupResponse:
    """1 時間キャッシュ付きでトレンドキャッチアップ結果を返す."""
    async with _lock:
        now = time.monotonic()
        cached = _cache.get("trend")
        if cached and now - cached[0] < _CACHE_TTL_SEC:
            return cached[1]

        result = await _compute_trend_catchup()
        _cache["trend"] = (now, result)
        return result


async def _compute_trend_catchup() -> TrendCatchupResponse:
    """全銘柄の週次リターンを計算し業種別トレンドを生成する.

    上場銘柄マスタ、または直近の株価データが 1 件も取れなかった場合は `JQuantsError` を
    送出する（系統的な取得失敗を「トレンド業種なし」の正常系空応答と区別する）。
    個別銘柄の取得失敗はベストエフォートで許容する。
    """
    today = datetime.date.today().strftime("%Y-%m-%d")

    all_stocks = await jquants.fetch_all_listed_stocks()
    if not all_stocks:
        raise JQuantsError("上場銘柄マスタを取得できませんでした")

    sector_map = _group_by_sector(all_stocks)
    sampled = _sample_stocks(sector_map)
    price_results = await _fetch_prices_parallel(sampled)

    sector_trends = _build_sector_trends(sector_map, price_results)
    if not sector_trends:
        raise JQuantsError(
            "直近の株価データを取得できませんでした。"
            "J-Quants が混雑しているか、契約プランの対象期間外の可能性があります"
        )

    uptrend = sorted(
        [s for s in sector_trends if s.direction == "up"],
        key=lambda s: s.avg_weekly_return,
        reverse=True,
    )
    downtrend = sorted(
        [s for s in sector_trends if s.direction == "down"],
        key=lambda s: s.avg_weekly_return,
    )

    return TrendCatchupResponse(as_of_date=today, uptrend_sectors=uptrend, downtrend_sectors=downtrend)


def _group_by_sector(stocks: list[JsonDict]) -> dict[str, _SectorInfo]:
    """銘柄リストを S33Nm（33 業種区分名）でグルーピングする."""
    groups: dict[str, _SectorInfo] = {}
    for s in stocks:
        sector_name = str(s.get("S33Nm") or s.get("S17Nm") or "その他")
        sector_code = str(s.get("S33") or s.get("S17") or "00")
        if not sector_name or sector_name in ("", "-", "－"):
            continue
        if sector_name not in groups:
            groups[sector_name] = {"code": sector_code, "stocks": []}
        groups[sector_name]["stocks"].append(s)
    return groups


def _sample_stocks(sector_map: dict[str, _SectorInfo]) -> list[tuple[str, str, str]]:
    """各業種から上位 N 銘柄を抽出して (code5, name, sector_name) のリストを返す."""
    sampled: list[tuple[str, str, str]] = []
    for sector_name, info in sector_map.items():
        for s in info["stocks"][:_MAX_STOCKS_PER_SECTOR]:
            code = str(s.get("Code", ""))
            name = str(s.get("CoName") or s.get("CoNameEn") or code)
            if code:
                sampled.append((code, name, sector_name))
    return sampled


async def _fetch_prices_parallel(stocks: list[tuple[str, str, str]]) -> dict[str, _PriceResult | None]:
    """全銘柄の週次価格を並列取得する（単一銘柄の失敗はベストエフォートで継続）."""
    sem = asyncio.Semaphore(_CONCURRENCY)

    async def fetch_one(code: str, name: str, sector: str) -> tuple[str, _PriceResult | None]:
        async with sem:
            try:
                df = await jquants.fetch_daily_quotes(code, period="2w")
            except JQuantsError:
                logger.debug("価格取得スキップ: %s", code)
                return code, None

        if df.empty or len(df) < 2:
            return code, None

        current = float(df["Close"].iloc[-1])
        week_ago = float(df["Close"].iloc[0])
        if week_ago == 0:
            return code, None

        weekly_return = (current / week_ago - 1) * 100
        return code, {
            "name": name,
            "sector": sector,
            "weekly_return": weekly_return,
            "current": current,
            "week_ago": week_ago,
        }

    tasks = [fetch_one(code, name, sector) for code, name, sector in stocks]
    results = await asyncio.gather(*tasks)
    return {code: data for code, data in results}


def _build_sector_trends(
    sector_map: dict[str, _SectorInfo],
    price_results: dict[str, _PriceResult | None],
) -> list[SectorTrend]:
    """価格データをもとに業種別トレンドオブジェクトを構築する."""
    trends: list[SectorTrend] = []

    for sector_name, info in sector_map.items():
        sector_code = info["code"]
        stocks = info["stocks"][:_MAX_STOCKS_PER_SECTOR]

        stock_trends: list[StockTrend] = []
        returns: list[float] = []

        for s in stocks:
            code = str(s.get("Code", ""))
            data = price_results.get(code)
            if not data:
                continue
            stock_trends.append(
                StockTrend(
                    code=code,
                    name=data["name"],
                    weekly_return=round(data["weekly_return"], 2),
                    current_price=round(data["current"], 1),
                    week_ago_price=round(data["week_ago"], 1),
                )
            )
            returns.append(data["weekly_return"])

        if not returns:
            continue

        avg_return = sum(returns) / len(returns)
        breadth = sum(1 for r in returns if r > 0) / len(returns) * 100
        direction = "up" if avg_return > 0.3 else "down" if avg_return < -0.3 else "neutral"
        top_stocks = sorted(stock_trends, key=lambda x: abs(x.weekly_return), reverse=True)[:3]
        reasoning = _generate_reasoning(sector_name, avg_return, breadth, len(returns))

        trends.append(
            SectorTrend(
                sector_code=sector_code,
                sector_name=sector_name,
                direction=direction,
                avg_weekly_return=round(avg_return, 2),
                breadth=round(breadth, 1),
                stock_count=len(returns),
                top_stocks=top_stocks,
                reasoning=reasoning,
            )
        )

    return trends


def _generate_reasoning(sector_name: str, avg_return: float, breadth: float, count: int) -> str:
    """週次リターンと騰落銘柄比率から自然言語の分析理由を生成する."""
    sign = "+" if avg_return >= 0 else ""
    ret_str = f"{sign}{avg_return:.1f}%"
    breadth_int = int(breadth)

    if avg_return > 3:
        trend_desc = "力強い上昇基調"
    elif avg_return > 1:
        trend_desc = "緩やかな上昇基調"
    elif avg_return > 0.3:
        trend_desc = "小幅な上昇傾向"
    elif avg_return < -3:
        trend_desc = "急速な下落基調"
    elif avg_return < -1:
        trend_desc = "明確な下落基調"
    elif avg_return < -0.3:
        trend_desc = "小幅な下落傾向"
    else:
        trend_desc = "横ばい"

    if breadth >= 70:
        breadth_desc = f"対象{count}銘柄の{breadth_int}%がプラスリターンを記録し、買い優勢の地合い"
    elif breadth >= 50:
        breadth_desc = f"対象{count}銘柄の{breadth_int}%がプラスリターンで、やや買いが優勢"
    elif breadth >= 30:
        breadth_desc = f"対象{count}銘柄の{breadth_int}%しかプラスリターンになっておらず、売り優勢"
    else:
        breadth_desc = f"対象{count}銘柄の{breadth_int}%のみプラスリターンで、売り圧力が高まっている"

    return f"直近 1 週間で{sector_name}業種の平均リターンは{ret_str}（{trend_desc}）。{breadth_desc}。"
