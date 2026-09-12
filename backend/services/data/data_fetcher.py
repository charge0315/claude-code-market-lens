"""株価データ取得・キャッシュ・銘柄検索サービス.

Market Lens `backend/services/data_fetcher.py` から移植（import パスのみ変更:
`models.schemas` → `models.stocks`、`services.cache` → `services.data.cache`、
`services.jquants_client` → `services.data.jquants_client` ほか）。
"""

from __future__ import annotations

import asyncio
import io
import logging
import re
import time
from typing import cast

import pandas as pd
import yfinance as yf
from yfinance.exceptions import YFRateLimitError

from backend.models.stocks import TickerInfo
from backend.services.circuit_breaker import CircuitBreaker
from backend.services.data.cache import stock_cache
from backend.services.data.data_fetcher_errors import StockCircuitOpenError, StockRateLimitError
from backend.services.data.jquants_client import jquants

logger = logging.getLogger(__name__)

_PRICE_CACHE_TTL: int = 300  # 株価データ: 5 分
_COMPANY_CACHE_TTL: int = 24 * 60 * 60  # 企業情報: 1 日
# マクロ指標（日経平均・USD/JPY・VIX 等）: 1 日。日次学習バッチ中にキャッシュが失効し続けて
# yfinance レート制限で停止しないよう、株価より長い TTL にする。
_MACRO_CACHE_TTL: int = 24 * 60 * 60

_YF_RETRY_MAX_ATTEMPTS: int = 3
_YF_RETRY_BASE_DELAY_SEC: float = 1.0
_YF_RETRY_BACKOFF_MULTIPLIER: float = 2.0

# yfinance 呼び出し専用のサーキットブレーカ（プロセス全体で状態を共有する）。
_yfinance_breaker: CircuitBreaker = CircuitBreaker(open_error_factory=StockCircuitOpenError)

_TICKER_MASTER_CACHE_TTL: int = 24 * 60 * 60
_ticker_master_cache: tuple[float, list[TickerInfo]] | None = None
_ticker_master_lock = asyncio.Lock()

# J-Quants 未設定・取得失敗時のフォールバック用主要銘柄。
MAJOR_JP_STOCKS: dict[str, TickerInfo] = {
    "7203": TickerInfo(code="7203", name="トヨタ自動車", sector="輸送用機器"),
    "6758": TickerInfo(code="6758", name="ソニーグループ", sector="電気機器"),
    "9984": TickerInfo(code="9984", name="ソフトバンクグループ", sector="情報・通信業"),
    "8306": TickerInfo(code="8306", name="三菱UFJフィナンシャル・グループ", sector="銀行業"),
    "6861": TickerInfo(code="6861", name="キーエンス", sector="電気機器"),
    "9432": TickerInfo(code="9432", name="日本電信電話", sector="情報・通信業"),
    "6501": TickerInfo(code="6501", name="日立製作所", sector="電気機器"),
    "7974": TickerInfo(code="7974", name="任天堂", sector="その他製品"),
    "4063": TickerInfo(code="4063", name="信越化学工業", sector="化学"),
    "8035": TickerInfo(code="8035", name="東京エレクトロン", sector="電気機器"),
    "9433": TickerInfo(code="9433", name="KDDI", sector="情報・通信業"),
    "4519": TickerInfo(code="4519", name="中外製薬", sector="医薬品"),
    "6098": TickerInfo(code="6098", name="リクルートホールディングス", sector="サービス業"),
    "6902": TickerInfo(code="6902", name="デンソー", sector="輸送用機器"),
    "4568": TickerInfo(code="4568", name="第一三共", sector="医薬品"),
}


# TSE の証券コードは通常 4 桁数字だが、優先株式は末尾に区分数字が付いた 5 桁、2024 年以降は
# 英数字混在の新形式（例: "166A"）もある。いずれも Yahoo Finance では末尾 .T で解決する。
# 純粋な英字のみのシンボルを誤って .T 化しないよう、少なくとも 1 桁は数字を含むことを条件にする。
_JP_TICKER_CODE_RE = re.compile(r"^(?=.*[0-9])[0-9A-Z]{4,5}$")


def ensure_ticker_suffix(ticker: str) -> str:
    """日本株の証券コード（数字 4〜5 桁・新形式の英数字混在）に TSE 市場サフィックスを付与する."""
    stripped = ticker.strip().upper()
    if _JP_TICKER_CODE_RE.fullmatch(stripped):
        return f"{stripped}.T"
    return ticker.strip()


def _fetch_history_with_retry(stock: yf.Ticker, ticker: str, period: str, interval: str) -> pd.DataFrame:
    """yfinance のレート制限（YFRateLimitError）に対して指数バックオフ付きでリトライする."""
    last_exc: YFRateLimitError | None = None
    for attempt in range(_YF_RETRY_MAX_ATTEMPTS):
        try:
            return stock.history(period=period, interval=interval)
        except YFRateLimitError as e:
            last_exc = e
            if attempt == _YF_RETRY_MAX_ATTEMPTS - 1:
                break
            delay = _YF_RETRY_BASE_DELAY_SEC * (_YF_RETRY_BACKOFF_MULTIPLIER**attempt)
            logger.warning(
                "yfinance レート制限のためリトライ %d/%d（%.1f 秒待機）: %s",
                attempt + 1,
                _YF_RETRY_MAX_ATTEMPTS,
                delay,
                ticker,
            )
            # asyncio.to_thread 経由の同期ワーカースレッド内で呼ばれるため time.sleep を使う。
            time.sleep(delay)

    if last_exc is None:
        raise RuntimeError("リトライループが例外なしで終了することはない")
    raise last_exc


def _fetch_yfinance_series(
    resolved_symbol: str, period: str, interval: str, cache_key: str, cache_ttl: int
) -> pd.DataFrame:
    """yfinance 時系列取得に共通する耐障害性（キャッシュ・リトライ・ブレーカ）を集約する."""
    if cache_ttl > 0:
        cached = stock_cache.get_dataframe(cache_key)
        if cached is not None:
            logger.info("キャッシュヒット: %s", cache_key)
            return cached

    logger.info("yfinance API へリクエスト: %s (period=%s, interval=%s)", resolved_symbol, period, interval)

    _yfinance_breaker.before_request()

    try:
        stock = yf.Ticker(resolved_symbol)
        df: pd.DataFrame = _fetch_history_with_retry(stock, resolved_symbol, period, interval)
    except YFRateLimitError as e:
        _yfinance_breaker.record_failure()
        logger.warning("yfinance レート制限でリトライ枯渇: %s", resolved_symbol)
        raise StockRateLimitError(resolved_symbol) from e
    except Exception:
        logger.exception("株価データ取得に失敗: %s", resolved_symbol)
        raise

    _yfinance_breaker.record_success()

    if df.empty:
        logger.warning("データ取得結果が空: %s", resolved_symbol)
        return df

    if cache_ttl > 0:
        stock_cache.set_dataframe(cache_key, df, ttl=cache_ttl)
    logger.info("取得成功: %s (%d 件)", resolved_symbol, len(df))
    return df


def fetch_stock_data(ticker: str, period: str, interval: str) -> pd.DataFrame:
    """yfinance 経由で株価 OHLCV データを取得する（SQLite キャッシュ + リトライ + ブレーカ）."""
    resolved_ticker = ensure_ticker_suffix(ticker)
    cache_key = f"price_{resolved_ticker}_{period}_{interval}"
    # period="max" は大きい割にヒット率が低くキャッシュ肥大の主因のため意図的にキャッシュしない。
    ttl = 0 if period == "max" else _PRICE_CACHE_TTL
    return _fetch_yfinance_series(resolved_ticker, period, interval, cache_key, ttl)


def fetch_macro_symbol_data(symbol: str, period: str = "5y", interval: str = "1d") -> pd.DataFrame:
    """マクロ市場指標（日経平均・USD/JPY・VIX など）を yfinance から取得する.

    シンボルは既に yfinance が受理する形式（例: "^N225"）で渡される前提のため
    ``ensure_ticker_suffix`` は適用しない。耐障害性は ``fetch_stock_data`` と共有する。
    """
    cache_key = f"macro_{symbol}_{period}_{interval}"
    return _fetch_yfinance_series(symbol, period, interval, cache_key, _MACRO_CACHE_TTL)


def get_company_info(ticker: str) -> dict[str, str | None] | None:
    """企業の基本情報（名称・セクター等）を yfinance から取得する（TTL 長め）."""
    resolved_ticker = ensure_ticker_suffix(ticker)
    cache_key = f"company_{resolved_ticker}"

    cached = stock_cache.get_json(cache_key)
    if cached is not None:
        logger.info("企業情報キャッシュヒット: %s", resolved_ticker)
        return cast("dict[str, str | None]", cached)

    try:
        stock = yf.Ticker(resolved_ticker)
        info: dict[str, object] = stock.info
        if not info:
            return None

        result: dict[str, str | None] = {
            "name": cast("str | None", info.get("longName") or info.get("shortName")),
            "sector": cast("str | None", info.get("sector")),
            "industry": cast("str | None", info.get("industry")),
            "currency": cast("str | None", info.get("currency")),
        }
        stock_cache.set_json(cache_key, result, ttl=_COMPANY_CACHE_TTL)
        return result
    except Exception:
        logger.exception("企業情報の取得に失敗: %s", resolved_ticker)
        return None


def parse_csv_data(file_content: bytes) -> pd.DataFrame:
    """アップロードされた CSV バイト列を DataFrame に変換し列名を正規化する."""
    df = pd.read_csv(io.BytesIO(file_content))
    column_mapping: dict[str, str] = {
        "date": "Date",
        "open": "Open",
        "high": "High",
        "low": "Low",
        "close": "Close",
        "volume": "Volume",
        "adj close": "Adj_Close",
    }
    normalized_columns = {col: column_mapping.get(col.strip().lower(), col) for col in df.columns}
    return df.rename(columns=normalized_columns)


def get_stock_data(ticker: str, period: str = "1y") -> pd.DataFrame:
    """日次 OHLCV データを取得する統合エントリーポイント."""
    return fetch_stock_data(ticker, period=period, interval="1d")


def _to_4digit_code(code: str) -> str:
    """J-Quants の 5 桁コード（普通株は末尾 0）を 4 桁コードへ戻す."""
    return code[:-1] if len(code) == 5 and code.endswith("0") else code


async def _get_ticker_master() -> list[TickerInfo]:
    """検索対象の銘柄マスタを返す（J-Quants 優先、24 時間キャッシュ、フォールバックあり）."""
    global _ticker_master_cache

    async with _ticker_master_lock:
        now = time.monotonic()
        if _ticker_master_cache and now - _ticker_master_cache[0] < _TICKER_MASTER_CACHE_TTL:
            return _ticker_master_cache[1]

        fallback = list(MAJOR_JP_STOCKS.values())
        if not jquants.is_configured:
            return fallback

        raw_stocks = await jquants.fetch_all_listed_stocks()
        if not raw_stocks:
            logger.warning("J-Quants 銘柄マスタが空のためフォールバックを使用します")
            return fallback

        tickers: list[TickerInfo] = []
        for row in raw_stocks:
            code = str(row.get("Code") or "")
            name = row.get("CoName") or row.get("CoNameEn")
            if not code or not name:
                continue
            sector = row.get("S33Nm") or row.get("S17Nm")
            tickers.append(TickerInfo(code=_to_4digit_code(code), name=str(name), sector=cast("str | None", sector)))

        if not tickers:
            return fallback

        _ticker_master_cache = (now, tickers)
        return tickers


_SEARCH_RESULT_LIMIT = 30


async def search_tickers(query: str) -> list[TickerInfo]:
    """銘柄マスタから証券コードまたは銘柄名で部分一致検索（最大 _SEARCH_RESULT_LIMIT 件）."""
    query_lower = query.strip().lower()
    if not query_lower:
        return []

    master = await _get_ticker_master()
    matches = (t for t in master if query_lower in t.code.lower() or query_lower in t.name.lower())
    result: list[TickerInfo] = []
    for t in matches:
        result.append(t)
        if len(result) >= _SEARCH_RESULT_LIMIT:
            break
    return result


async def get_company_name(code: str) -> str | None:
    """指定コードの銘柄名を銘柄マスタ（24h キャッシュ）から引く（表示専用の付加情報）.

    ピック一覧・ピック詳細 API は台帳（`prediction_ledger`）に銘柄名を保存していない
    （予測時点の確定情報のみを永続化する方針、CL-1）ため、表示時にここから都度引く。
    """
    master = await _get_ticker_master()
    return next((t.name for t in master if t.code == code), None)
