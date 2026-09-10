"""TrendCollector — 外部トピック / シグナルの収集層.

Market Lens `backend/services/trend/collector.py` から移植。変更点（🔧）:
- `dashboard_service._INDEX_DEFINITIONS` 依存を排し、指数シンボルをこのモジュール内の
  定数 `_INDEX_SYMBOLS` に固定（`dashboard_service` は未移植のため）。
- import パスを Alpha Forge 構成へ（`services.data.ranking_service` / `services.data.trend_service`）。

v1 のソース（いずれもベストエフォート、無料・API キー不要）:
  1. yfinance のニュース見出し（主要指数 + 当日の値動き上位銘柄）を集約・重複排除
  2. `trend_service.get_trend_catchup()` のセクター騰落 + reasoning
全滅時（ニュース 0 件かつ trend_service 不可）は `_MOCK_SIGNALS` を返す。
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field

import yfinance as yf

from backend.services.data import ranking_service, trend_service
from backend.services.data.jquants_errors import JQuantsError

logger = logging.getLogger(__name__)

# ニュース見出しを引く指数（`^VIX` は日経VI 代替、`JPY=X` はドル円）。
_INDEX_SYMBOLS: tuple[str, ...] = ("^N225", "^TPX", "JPY=X", "^VIX")

_MOVERS_PER_SIDE = 6
_MAX_HEADLINES = 60
_RANKING_POOL = 30


@dataclass(frozen=True)
class CollectedSignals:
    """アナライザーへ渡す収集結果."""

    headlines: list[str] = field(default_factory=list)
    sector_notes: list[str] = field(default_factory=list)
    source_summary: str = ""
    is_mock: bool = False

    @property
    def signal_count(self) -> int:
        return len(self.headlines) + len(self.sector_notes)


# ネットワーク / キー無しでも全体を通せるようにするフォールバック（固定・決定論的）。
_MOCK_SIGNALS: tuple[str, ...] = (
    "次世代半導体パッケージング（CoWoS/チップレット）で後工程装置に受注拡大観測",
    "生成AIデータセンター向け電力・液冷需要が急伸、関連部材メーカーに買い",
    "防衛費増額を背景に防衛関連の中期成長期待が再燃",
    "インバウンド消費が過去最高圏、百貨店・鉄道・ホテルに追い風",
    "円安一服で輸出採算に一服感、内需・ディフェンシブへ資金シフトの兆し",
    "電力設備の更新投資サイクル入り、送配電・重電に長期テーマ",
    "肥満症治療薬（GLP-1）の国内展開進展で医薬・受託製造に思惑",
    "国産クラウド/経済安全保障関連のソフトウェア投資が拡大",
)


def _fetch_news_titles(symbol: str) -> list[str]:
    """1 シンボルのニュース見出しを返す（sentiment_analyzer と同じ yfinance 経路）."""
    try:
        raw = yf.Ticker(symbol).news or []
    except Exception:  # noqa: BLE001 — ベストエフォート。1 銘柄の失敗で全体を止めない
        return []
    titles: list[str] = []
    for item in raw:
        title = item.get("title") or (item.get("content") or {}).get("title")
        if isinstance(title, str) and title.strip():
            titles.append(title.strip())
    return titles


async def _collect_headlines() -> list[str]:
    symbols: list[str] = list(_INDEX_SYMBOLS)
    try:
        rankings = await ranking_service.get_rankings(_RANKING_POOL)
        movers = rankings.gainers[:_MOVERS_PER_SIDE] + rankings.losers[:_MOVERS_PER_SIDE]
        symbols += [f"{e.code}.T" if not e.code.endswith(".T") else e.code for e in movers]
    except Exception:  # noqa: BLE001 — ランキング取得失敗は指数分だけで続行
        logger.warning("トレンド収集: ランキング取得に失敗（指数分のみで継続）", exc_info=True)

    results = await asyncio.gather(
        *[asyncio.to_thread(_fetch_news_titles, s) for s in dict.fromkeys(symbols)],
        return_exceptions=True,
    )
    seen: set[str] = set()
    headlines: list[str] = []
    for res in results:
        if isinstance(res, BaseException):
            continue
        for title in res:
            key = title.lower()
            if key in seen:
                continue
            seen.add(key)
            headlines.append(title)
    return headlines[:_MAX_HEADLINES]


async def _collect_sector_notes() -> list[str]:
    try:
        catchup = await trend_service.get_trend_catchup()
    except JQuantsError:
        return []
    except Exception:  # noqa: BLE001
        logger.warning("トレンド収集: セクター騰落の取得に失敗", exc_info=True)
        return []
    notes: list[str] = []
    for sector in list(catchup.uptrend_sectors[:6]) + list(catchup.downtrend_sectors[:6]):
        arrow = "上昇" if sector.direction == "up" else "下降" if sector.direction == "down" else "横ばい"
        notes.append(
            f"[{arrow}] {sector.sector_name}: 週次平均{sector.avg_weekly_return:+.2f}% "
            f"(breadth {sector.breadth:.0%}) — {sector.reasoning}"
        )
    return notes


async def collect_signals() -> CollectedSignals:
    """全ソースをベストエフォートで集約する（全滅時はモックを返す）."""
    headlines, sector_notes = await asyncio.gather(_collect_headlines(), _collect_sector_notes())

    if not headlines and not sector_notes:
        logger.info("トレンド収集: 実シグナル 0 件のためモックデータセットを使用")
        return CollectedSignals(
            headlines=list(_MOCK_SIGNALS),
            sector_notes=[],
            source_summary="モック（急上昇トレンド生成データセット）",
            is_mock=True,
        )

    summary = f"ニュース見出し {len(headlines)}件 / セクター騰落 {len(sector_notes)}件"
    return CollectedSignals(headlines=headlines, sector_notes=sector_notes, source_summary=summary, is_mock=False)
