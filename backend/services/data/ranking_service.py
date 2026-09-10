"""企業ランキング・年間値上がり率 TOP10 サービス.

Market Lens `backend/services/ranking_service.py` から移植（import パスのみ変更）。
Alpha Forge では中長期 / 短期ピックの候補プール生成の母集団としても使う（P3）。

要点（Market Lens の検証スパイク結論）:
- J-Quants V2 `/equities/bars/daily` は `code` を省略し `date` のみ指定すると、その日の
  全上場銘柄（約 4400 銘柄）を 1 リクエストで返す（ページネーションなし）。非営業日は
  200 + 空リストで返るため「空なら 1 営業日遡る」で直近取引日を解決できる。
- 契約プランによっては配信が数週間遅延する。J-Quants が返す 400 エラー本文
  （"covers the following dates: X ~ Y"）から実データ範囲を抽出し、境界日を起点に
  やり直す（`_walk_back_with_subscription_fallback`）。
- 銘柄名解決に失敗した回のレスポンスはキャッシュしない（コード表示のまま固定される不具合対策）。
"""

from __future__ import annotations

import asyncio
import datetime
import logging
import re
import time
from typing import TypedDict

from backend.models.dashboard import (
    MarketBreadth,
    RankingEntry,
    RankingsResponse,
    YearlyPerformanceEntry,
    YearlyPerformanceResponse,
)
from backend.models.jquants_raw import coerce_optional_float
from backend.services.data.data_fetcher import _to_4digit_code
from backend.services.data.jquants_client import JsonDict, jquants
from backend.services.data.jquants_errors import JQuantsClientError, JQuantsError

logger = logging.getLogger(__name__)

# 非営業日を遡って直近の取引日を探す際の最大遡り日数。
_MAX_LOOKBACK_DAYS = 7

# キャッシュは上限件数で保持し、limit スライスはリクエスト時に行う。
_POOL_SIZE = 50

_RANKINGS_CACHE_TTL_SEC = 24 * 60 * 60
_YEARLY_CACHE_TTL_SEC = 24 * 60 * 60
_NAME_MAP_CACHE_TTL_SEC = 24 * 60 * 60
_LATEST_DATE_CACHE_TTL_SEC = 24 * 60 * 60

# 400 エラー本文から契約プランのカバー範囲 (下限, 上限) を抽出する。
_SUBSCRIPTION_RANGE_PATTERN = re.compile(
    r"covers the following dates:\s*([\d]{4}-[\d]{2}-[\d]{2})\s*~\s*([\d]{4}-[\d]{2}-[\d]{2})"
)

_rankings_cache: tuple[float, RankingsResponse] | None = None
_rankings_lock = asyncio.Lock()

_yearly_cache: tuple[float, YearlyPerformanceResponse] | None = None
_yearly_lock = asyncio.Lock()

_name_map_cache: tuple[float, dict[str, str]] | None = None
_latest_date_cache: tuple[float, str, list[JsonDict]] | None = None
_latest_date_lock = asyncio.Lock()


class _CodeSnapshot(TypedDict):
    close: float
    volume: float


async def get_rankings(limit: int) -> RankingsResponse:
    """1 日キャッシュ付きで日次ランキングを返す（limit はキャッシュ後にスライス）."""
    global _rankings_cache
    full: RankingsResponse
    async with _rankings_lock:
        now = time.monotonic()
        cached = _rankings_cache
        if cached and now - cached[0] < _RANKINGS_CACHE_TTL_SEC:
            full = cached[1]
        else:
            full, names_resolved = await _compute_rankings(_POOL_SIZE)
            if names_resolved:
                _rankings_cache = (now, full)
    return _slice_rankings(full, limit)


async def get_yearly_performance(limit: int) -> YearlyPerformanceResponse:
    """1 日キャッシュ付きで年間値上がり率 TOP10 を返す（limit はキャッシュ後にスライス）."""
    global _yearly_cache
    full: YearlyPerformanceResponse
    async with _yearly_lock:
        now = time.monotonic()
        cached = _yearly_cache
        if cached and now - cached[0] < _YEARLY_CACHE_TTL_SEC:
            full = cached[1]
        else:
            full, names_resolved = await _compute_yearly_performance(_POOL_SIZE)
            if names_resolved:
                _yearly_cache = (now, full)
    return _slice_yearly(full, limit)


def _slice_rankings(full: RankingsResponse, limit: int) -> RankingsResponse:
    return full.model_copy(
        update={
            "gainers": full.gainers[:limit],
            "losers": full.losers[:limit],
            "volume_leaders": full.volume_leaders[:limit],
        }
    )


def _slice_yearly(full: YearlyPerformanceResponse, limit: int) -> YearlyPerformanceResponse:
    return full.model_copy(update={"top": full.top[:limit]})


# --- 日次ランキング ---


async def _compute_rankings(pool_size: int) -> tuple[RankingsResponse, bool]:
    """直近 2 営業日分の全銘柄一括取得から、値上がり / 値下がり / 出来高ランキングを計算する.

    戻り値の第 2 要素は銘柄名解決が成功したかどうか（失敗回はキャッシュしない）。
    """
    today_date, today_bars = await _resolve_latest_available()
    _, prev_bars = await _walk_back_with_subscription_fallback(
        datetime.date.fromisoformat(today_date) - datetime.timedelta(days=1)
    )

    prev_by_code = _index_by_code(prev_bars)
    name_by_code = await _fetch_name_map()
    names_resolved = bool(name_by_code)

    entries: list[RankingEntry] = []
    advancers = 0
    decliners = 0
    unchanged = 0

    for bar in today_bars:
        code = str(bar.get("Code") or "")
        close = coerce_optional_float(bar.get("AdjC"))
        volume = coerce_optional_float(bar.get("AdjVo"))
        if not code or close is None:
            continue

        prev = prev_by_code.get(code)
        if prev is None or not prev["close"]:
            # 前営業日に存在しない銘柄（新規上場等）は前日比が計算できないため除外。
            continue

        change_percent = (close - prev["close"]) / prev["close"] * 100
        if change_percent > 0:
            advancers += 1
        elif change_percent < 0:
            decliners += 1
        else:
            unchanged += 1

        entries.append(
            RankingEntry(
                code=_to_4digit_code(code),
                name=name_by_code.get(code, code),
                close=round(close, 1),
                change_percent=round(change_percent, 2),
                volume=int(volume or 0),
            )
        )

    if not entries:
        raise JQuantsError("日次ランキングを計算できる銘柄がありませんでした")

    gainers = sorted(entries, key=lambda e: e.change_percent, reverse=True)[:pool_size]
    losers = sorted(entries, key=lambda e: e.change_percent)[:pool_size]
    volume_leaders = sorted(entries, key=lambda e: e.volume, reverse=True)[:pool_size]

    breadth = MarketBreadth(
        advancers=advancers,
        decliners=decliners,
        unchanged=unchanged,
        comment=_generate_breadth_comment(advancers, decliners),
    )

    return (
        RankingsResponse(
            as_of_date=today_date,
            market_breadth=breadth,
            gainers=gainers,
            losers=losers,
            volume_leaders=volume_leaders,
        ),
        names_resolved,
    )


def _generate_breadth_comment(advancers: int, decliners: int) -> str:
    """値上がり / 値下がり銘柄数から地合いの一言コメントを生成する純関数."""
    if advancers > decliners:
        tendency = "買い優勢"
    elif decliners > advancers:
        tendency = "売り優勢"
    else:
        tendency = "拮抗"
    return f"値上がり{advancers}銘柄・値下がり{decliners}銘柄で、本日は{tendency}。"


# --- 年間値上がり率 TOP10 ---


async def _compute_yearly_performance(pool_size: int) -> tuple[YearlyPerformanceResponse, bool]:
    """「本日」と「約 1 年前の取引日」の 2 回の一括取得から年間リターンを計算する."""
    as_of_date, today_bars = await _resolve_latest_available()
    today = datetime.date.fromisoformat(as_of_date)
    target_base = today - datetime.timedelta(days=365)
    base_date, base_bars = await _walk_back_with_subscription_fallback(target_base)

    base_by_code = _index_by_code(base_bars)
    name_by_code = await _fetch_name_map()
    names_resolved = bool(name_by_code)

    entries: list[YearlyPerformanceEntry] = []
    for bar in today_bars:
        code = str(bar.get("Code") or "")
        end_price = coerce_optional_float(bar.get("AdjC"))
        if not code or end_price is None:
            continue

        base = base_by_code.get(code)
        if base is None or not base["close"]:
            continue

        start_price = base["close"]
        yearly_return = (end_price / start_price - 1) * 100

        entries.append(
            YearlyPerformanceEntry(
                code=_to_4digit_code(code),
                name=name_by_code.get(code, code),
                yearly_return=round(yearly_return, 2),
                start_price=round(start_price, 1),
                end_price=round(end_price, 1),
            )
        )

    if not entries:
        raise JQuantsError("年間値上がり率を計算できる銘柄がありませんでした")

    top = sorted(entries, key=lambda e: e.yearly_return, reverse=True)[:pool_size]

    return (
        YearlyPerformanceResponse(
            as_of_date=as_of_date,
            base_date=base_date,
            universe="all",
            universe_size=len(entries),
            top=top,
        ),
        names_resolved,
    )


# --- 共通ヘルパー ---


async def _resolve_latest_available() -> tuple[str, list[JsonDict]]:
    """契約プランの配信遅延を吸収し、実データが存在する直近取引日とその日の bars を解決する."""
    global _latest_date_cache
    async with _latest_date_lock:
        now = time.monotonic()
        cached = _latest_date_cache
        if cached and now - cached[0] < _LATEST_DATE_CACHE_TTL_SEC:
            return cached[1], cached[2]

        latest_date, bars = await _walk_back_with_subscription_fallback(datetime.date.today())
        _latest_date_cache = (now, latest_date, bars)
        return latest_date, bars


async def _walk_back_with_subscription_fallback(start: datetime.date) -> tuple[str, list[JsonDict]]:
    """`_walk_back_for_bars` を試み、契約プラン範囲外（400）の場合のみ境界日で再試行する.

    パターンに一致しない 400（認証エラー等）はそのまま再送出する。
    """
    try:
        return await _walk_back_for_bars(start)
    except JQuantsClientError as e:
        bounds = _parse_subscription_range(e)
        if bounds is None:
            raise
        lower_bound, upper_bound = bounds
        fallback = upper_bound if start.isoformat() > upper_bound else lower_bound
        logger.info(
            "契約プラン範囲外を検知（範囲: %s ~ %s）。%s を起点に再解決します",
            lower_bound,
            upper_bound,
            fallback,
        )
        return await _walk_back_for_bars(datetime.date.fromisoformat(fallback))


def _parse_subscription_range(exc: JQuantsClientError) -> tuple[str, str] | None:
    """400 エラー本文から契約プランのカバー範囲 (下限, 上限) を抽出する（一致しなければ None）."""
    match = _SUBSCRIPTION_RANGE_PATTERN.search(exc.body)
    if match is None:
        return None
    return match.group(1), match.group(2)


async def _walk_back_for_bars(start: datetime.date) -> tuple[str, list[JsonDict]]:
    """指定日から最大 `_MAX_LOOKBACK_DAYS` 日遡り、データが存在する直近の取引日を探す.

    非営業日は J-Quants が 200 + 空リストで返すため前日へ遡る。インフラ / 上流障害を示す
    `JQuantsError` は遡らず即座に伝播させる（「取得失敗」と「非営業日が続いた」を混同しない）。
    """
    date = start
    for _ in range(_MAX_LOOKBACK_DAYS):
        date_str = date.isoformat()
        bars = await jquants.fetch_all_daily_bars(date_str)
        if bars:
            return date_str, bars
        logger.info("非営業日のためスキップ: %s", date_str)
        date -= datetime.timedelta(days=1)

    raise JQuantsError(f"直近{_MAX_LOOKBACK_DAYS}日以内の取引日データを取得できませんでした")


def _index_by_code(bars: list[JsonDict]) -> dict[str, _CodeSnapshot]:
    """全銘柄一括取得の生レコード列を code をキーにした終値 / 出来高の辞書に変換する."""
    result: dict[str, _CodeSnapshot] = {}
    for bar in bars:
        code = str(bar.get("Code") or "")
        close = coerce_optional_float(bar.get("AdjC"))
        if not code or close is None:
            continue
        volume = coerce_optional_float(bar.get("AdjVo")) or 0.0
        result[code] = {"close": close, "volume": volume}
    return result


async def _fetch_name_map() -> dict[str, str]:
    """銘柄コード（J-Quants 5 桁形式）→ 銘柄名の対応表を 24 時間キャッシュ付きで返す.

    `fetch_all_listed_stocks()` は一時障害を握りつぶし空リストを返す契約のため、
    空の対応表はキャッシュせず次回再取得させる（コード表示のまま固定化を防ぐ）。
    """
    global _name_map_cache
    now = time.monotonic()
    if _name_map_cache and now - _name_map_cache[0] < _NAME_MAP_CACHE_TTL_SEC:
        return _name_map_cache[1]

    stocks = await jquants.fetch_all_listed_stocks()
    mapping = {str(s["Code"]): str(s.get("CoName") or s.get("CoNameEn") or s["Code"]) for s in stocks if s.get("Code")}
    if mapping:
        _name_map_cache = (now, mapping)
    return mapping
