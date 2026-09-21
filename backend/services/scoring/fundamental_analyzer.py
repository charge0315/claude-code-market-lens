"""ファンダメンタル分析サービス（yfinance + Obsidian Vault frontmatter フォールバック）.

Market Lens `backend/services/fundamental_analyzer.py` から移植。変更点（🔧）:
- `services.cache` → `services.data.cache`。
- 四季報スタブ期間（`SHIKIHO_ENABLED=false`）は fundamental の主データ源が
  Vault `Tickers/*.md` の frontmatter 財務指標 + J-Quants になる（`plans/00` §2.3）。
  `get_fundamental_with_vault_fallback` で yfinance が欠損した指標を Vault frontmatter の
  構造化フィールドで補完する（本文の生テキストは注入しない）。
- 🆕 `employees`（yfinance `fullTimeEmployees`）の欠損時、EDINET 有価証券報告書由来の
  `note.edinet_employee_count`（`brand_notes_service` が frontmatter から抽出済み）で
  補完する。PER/PBR 等の会計指標そのものへの EDINET 由来数値（実績配当・自己株式取得額・
  研究開発費等）の反映は、定量スコア式（`recommender.py` の `ロジックは変更なし`）ではなく
  `brand_frontmatter`（`BrandNote.to_prompt_dict()`）経由で LLM 深掘りプロンプト・
  `feature_snapshot` へ渡す（`orchestrator.py` の `_pit_fundamental_snapshot`）。
"""

from __future__ import annotations

import asyncio
import logging
from typing import cast

import yfinance as yf

from backend.services.data.cache import stock_cache
from backend.services.vault.brand_notes_service import BrandNote, get_brand_note

logger = logging.getLogger(__name__)

_FUNDAMENTAL_CACHE_TTL = 24 * 60 * 60


def get_fundamental_data(ticker: str) -> dict[str, str | float | int | None]:
    """指定銘柄のファンダメンタル指標を yfinance から取得する（1 日キャッシュ）."""
    jt = ticker if ticker.endswith(".T") else f"{ticker}.T"
    cache_key = f"fundamental_{jt}"

    cached = stock_cache.get_json(cache_key)
    if cached is not None:
        logger.info("ファンダメンタル指標キャッシュヒット: %s", jt)
        return cast("dict[str, str | float | int | None]", cached)

    try:
        stock = yf.Ticker(jt)
        info = stock.info
    except Exception as e:
        logger.warning("yfinance 情報取得エラー: %s — %s", jt, e)
        info = {}

    def safe_float(key: str) -> float | None:
        val = info.get(key)
        if val is None:
            return None
        try:
            return float(val)
        except (TypeError, ValueError):
            return None

    def safe_int(key: str) -> int | None:
        val = info.get(key)
        if val is None:
            return None
        try:
            return int(val)
        except (TypeError, ValueError):
            return None

    per = safe_float("trailingPE") or safe_float("forwardPE")

    # yfinance の dividendYield はパーセント表記（例: 3.54）で返るため、roe/roa と同じ
    # 小数比率（0.0354）へ揃える（フロントの ×100 表示や recommender の閾値判定のため）。
    dividend_yield_raw = safe_float("dividendYield")
    dividend_yield = dividend_yield_raw / 100 if dividend_yield_raw is not None else None

    result: dict[str, str | float | int | None] = {
        "ticker": ticker,
        "company_name": info.get("longName") or info.get("shortName"),
        "sector": info.get("sector"),
        "industry": info.get("industry"),
        "market_cap": safe_float("marketCap"),
        "per": per,
        "pbr": safe_float("priceToBook"),
        "roe": safe_float("returnOnEquity"),
        "roa": safe_float("returnOnAssets"),
        "dividend_yield": dividend_yield,
        "eps": safe_float("trailingEps"),
        "revenue": safe_float("totalRevenue"),
        "operating_margin": safe_float("operatingMargins"),
        "profit_margin": safe_float("profitMargins"),
        "debt_to_equity": safe_float("debtToEquity"),
        "current_ratio": safe_float("currentRatio"),
        "beta": safe_float("beta"),
        "high_52w": safe_float("fiftyTwoWeekHigh"),
        "low_52w": safe_float("fiftyTwoWeekLow"),
        "employees": safe_int("fullTimeEmployees"),
        "source": "yfinance",
    }

    if info:
        stock_cache.set_json(cache_key, result, ttl=_FUNDAMENTAL_CACHE_TTL)

    return result


def _as_ratio(value: float | None) -> float | None:
    """パーセント表記らしき値（絶対値 > 1）を小数比率へ、それ以外はそのまま返す."""
    if value is None:
        return None
    return value / 100 if abs(value) > 1 else value


def _merge_from_vault(
    base: dict[str, str | float | int | None], note: BrandNote
) -> dict[str, str | float | int | None]:
    """yfinance で欠損した指標のみを Vault frontmatter の構造化フィールドで補完する.

    yfinance と単位が揃うもの（PER / PBR / EPS）はそのまま、比率系（ROE / 配当利回り）は
    パーセント表記を小数比率へ正規化して埋める。市場は 1e8（億円 → 円）換算。
    補完した項目名は ``vault_filled`` に列挙し、由来を追跡可能にする。
    """
    merged = dict(base)
    filled: list[str] = []

    candidates: dict[str, float | None] = {
        "per": note.per_forecast,
        "pbr": note.pbr,
        "eps": note.eps_forecast,
        "roe": _as_ratio(note.roe),
        "dividend_yield": _as_ratio(note.dividend_yield_forecast),
        "market_cap": note.market_cap_oku * 1e8 if note.market_cap_oku is not None else None,
    }
    for key, value in candidates.items():
        if merged.get(key) is None and value is not None:
            merged[key] = value
            filled.append(key)

    if merged.get("company_name") is None and note.name is not None:
        merged["company_name"] = note.name
        filled.append("company_name")
    if merged.get("sector") is None and note.sector33 is not None:
        merged["sector"] = note.sector33
        filled.append("sector")
    if merged.get("employees") is None and note.edinet_employee_count is not None:
        merged["employees"] = note.edinet_employee_count
        filled.append("employees")

    if filled:
        merged["source"] = "yfinance+vault"
        merged["vault_filled"] = ",".join(filled)
    return merged


async def get_fundamental_with_vault_fallback(ticker: str) -> dict[str, str | float | int | None]:
    """yfinance の指標を Vault `Tickers/*.md` frontmatter で補完して返す（四季報スタブ期間の主経路）."""
    # get_fundamental_data は yf.Ticker(...).info を同期的に叩く（ブロッキング I/O）ため、
    # to_thread に逃がさないとピック生成ループ全体でイベントループを占有してしまう。
    base = await asyncio.to_thread(get_fundamental_data, ticker)
    note = await get_brand_note(ticker.replace(".T", ""))
    if note is None:
        return base
    return _merge_from_vault(base, note)
