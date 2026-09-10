"""yfinance ニュースを用いたキーワードベースのセンチメント分析サービス.

Market Lens `backend/services/sentiment_analyzer.py` から移植（import パスのみ変更:
`services.cache` → `services.data.cache`）。

FinBERT 等の本格 NLP は使わず見出しのキーワードカウントで判定するため、記事が少ない
銘柄の断定的なスコアは信頼度シュリンケージで中立（0.5）へ引き戻す。
"""

from __future__ import annotations

import datetime
import logging
from typing import TypedDict, cast

import yfinance as yf

from backend.services.data.cache import stock_cache

logger = logging.getLogger(__name__)

_SENTIMENT_CACHE_TTL = 24 * 60 * 60

# この件数以上ニュースがあれば raw スコアを全面的に信頼する。
_SHRINKAGE_FULL_CONFIDENCE_COUNT = 10


class NewsItemDict(TypedDict):
    """ニュース 1 件分のセンチメント分析結果."""

    title: str
    source: str
    published: str
    url: str
    score: float
    label: str


class SentimentSummaryDict(TypedDict):
    """センチメント分析の集計結果."""

    ticker: str
    total: int
    positive: int
    neutral: int
    negative: int
    average_score: float
    raw_average_score: float
    confidence: float
    news: list[NewsItemDict]


_POSITIVE_KEYWORDS: tuple[str, ...] = (
    "上昇", "上がる", "増益", "好調", "最高値", "黒字", "成長", "拡大", "回復", "好業績",
    "増加", "高騰", "好転", "上方修正", "増配", "買い", "強気", "急騰", "大幅増",
    "profit", "growth", "rise", "surge", "record", "gain", "beat", "rally", "strong",
    "upgrade", "positive", "outperform", "exceed", "milestone", "breakout",
)  # fmt: skip

_NEGATIVE_KEYWORDS: tuple[str, ...] = (
    "下落", "下がる", "減益", "悪化", "最安値", "赤字", "縮小", "低下", "損失", "不振",
    "減少", "暴落", "悪転", "下方修正", "減配", "売り", "弱気", "急落", "大幅減", "倒産",
    "リスク", "警告", "loss", "fall", "drop", "decline", "miss", "warn", "cut", "weak",
    "downgrade", "negative", "underperform", "struggle", "concern",
)  # fmt: skip


def _score_text(text: str) -> tuple[float, str]:
    """テキストのセンチメントスコア (score 0.0〜1.0, label positive/neutral/negative) を返す."""
    lower = text.lower()
    pos = sum(1 for kw in _POSITIVE_KEYWORDS if kw in lower)
    neg = sum(1 for kw in _NEGATIVE_KEYWORDS if kw in lower)
    total = pos + neg

    if total == 0:
        return 0.5, "neutral"

    score = pos / total
    if score >= 0.6:
        return round(score, 3), "positive"
    if score <= 0.4:
        return round(score, 3), "negative"
    return round(score, 3), "neutral"


def _apply_confidence_shrinkage(raw_score: float, article_count: int) -> float:
    """記事件数に応じて raw スコアを中立値 (0.5) へ縮小する（少数サンプルの断定を弱める）."""
    confidence = min(1.0, article_count / _SHRINKAGE_FULL_CONFIDENCE_COUNT)
    return 0.5 + (raw_score - 0.5) * confidence


def get_news_sentiment(ticker: str, max_items: int = 20) -> SentimentSummaryDict:
    """指定銘柄のニュースセンチメントを分析する（1 日キャッシュ、取得失敗はキャッシュしない）."""
    jt = ticker if ticker.endswith(".T") else f"{ticker}.T"
    cache_key = f"sentiment_{jt}_{max_items}"

    cached = stock_cache.get_json(cache_key)
    if cached is not None:
        logger.info("センチメントキャッシュヒット: %s", jt)
        return cast("SentimentSummaryDict", cached)

    try:
        stock = yf.Ticker(jt)
        raw_news = stock.news or []
    except Exception as e:
        logger.warning("ニュース取得エラー: %s — %s", jt, e)
        raw_news = []

    news_items: list[NewsItemDict] = []
    pos_count = neg_count = neutral_count = 0
    score_total = 0.0

    for item in raw_news[:max_items]:
        title = item.get("title", "")
        if not title:
            continue

        score, label = _score_text(title)

        pub_ts = item.get("providerPublishTime") or item.get("publishedTime")
        if pub_ts:
            pub_str = datetime.datetime.fromtimestamp(pub_ts, tz=datetime.UTC).strftime("%Y-%m-%d %H:%M")
        else:
            pub_str = ""

        news_items.append(
            {
                "title": title,
                "source": item.get("publisher", ""),
                "published": pub_str,
                "url": item.get("link", ""),
                "score": score,
                "label": label,
            }
        )

        if label == "positive":
            pos_count += 1
        elif label == "negative":
            neg_count += 1
        else:
            neutral_count += 1
        score_total += score

    total = len(news_items)
    raw_avg_score = round(score_total / total, 3) if total > 0 else 0.5
    avg_score = round(_apply_confidence_shrinkage(raw_avg_score, total), 3) if total > 0 else 0.5
    confidence = round(min(1.0, total / _SHRINKAGE_FULL_CONFIDENCE_COUNT), 3) if total > 0 else 0.0

    result: SentimentSummaryDict = {
        "ticker": ticker,
        "total": total,
        "positive": pos_count,
        "neutral": neutral_count,
        "negative": neg_count,
        "average_score": avg_score,
        "raw_average_score": raw_avg_score,
        "confidence": confidence,
        "news": news_items,
    }

    if raw_news:
        stock_cache.set_json(cache_key, result, ttl=_SENTIMENT_CACHE_TTL)

    return result
