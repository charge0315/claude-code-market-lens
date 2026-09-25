"""yfinance ニュースを用いたキーワードベースのセンチメント分析サービス.

Market Lens `backend/services/sentiment_analyzer.py` から移植（import パスのみ変更:
`services.cache` → `services.data.cache`）。

FinBERT 等の本格 NLP は使わず見出しのキーワードカウントで判定するため、記事が少ない
銘柄の断定的なスコアは信頼度シュリンケージで中立（0.5）へ引き戻す。

🔧 yfinance のニュース応答は、以前は `title`/`publisher`/`link`/`providerPublishTime` が
アイテム直下にあったが、現行版では `content` オブジェクトへネストされ（`content.title` /
`content.provider.displayName` / `content.canonicalUrl.url` / `content.pubDate`(ISO8601)）、
旧フィールド名では常に空文字列しか取れず全銘柄でニュース 0 件扱いになっていた
（2026-09-18 実機確認で発覚）。`_extract_content` で両形式を吸収する。

🔧 Yahoo がニュース API を遮断（HTTP 999 `Request denied`）すると、yfinance は例外を投げず
ERROR ログを出して空リストを返すため、「取得失敗」と「ニュース 0 件」が区別できず、
PIT 台帳に `news_count=0` の偽データが書かれていた（2026-09-26 発覚）。`_fetch_raw_news` が
自スレッドの yfinance 失敗ログを検知して `NewsFetchError` にし、`strict=True` の呼び出し元
（PIT 収集）へ伝える。
"""

from __future__ import annotations

import datetime
import logging
import threading
from typing import TypedDict, cast

import yfinance as yf

from backend.services.data.cache import stock_cache

logger = logging.getLogger(__name__)

_SENTIMENT_CACHE_TTL = 24 * 60 * 60

# この件数以上ニュースがあれば raw スコアを全面的に信頼する。
_SHRINKAGE_FULL_CONFIDENCE_COUNT = 10

# yfinance 1.7.0 `TickerBase.get_news` が非 JSON 応答（遮断ページ等）を握り潰すときの ERROR ログ文言。
_YF_NEWS_FAILURE_MARKER = "Failed to retrieve the news"


class NewsFetchError(RuntimeError):
    """ニュースを取得できなかった（「ニュースが 0 件だった」とは区別する）."""


class _NewsFailureDetector(logging.Handler):
    """このスレッドで出た yfinance のニュース取得失敗ログを検知する.

    FastAPI は `asyncio.to_thread` で並行に呼ぶため、他スレッドの失敗を自分の失敗と誤認しないよう
    スレッド ID で絞る。
    """

    def __init__(self) -> None:
        super().__init__(level=logging.ERROR)
        self._thread_id = threading.get_ident()
        self.detected = False

    def emit(self, record: logging.LogRecord) -> None:
        if record.thread == self._thread_id and _YF_NEWS_FAILURE_MARKER in record.getMessage():
            self.detected = True


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


def _extract_content(item: dict[str, object]) -> dict[str, object]:
    """yfinance ニュース1件の実データを取り出す（新形式は `content` にネスト、旧形式は直下）."""
    content = item.get("content")
    return content if isinstance(content, dict) else item


def _extract_source(content: dict[str, object]) -> str:
    provider = content.get("provider")
    if isinstance(provider, dict):
        name = provider.get("displayName")
        if isinstance(name, str) and name:
            return name
    publisher = content.get("publisher")
    return publisher if isinstance(publisher, str) else ""


def _extract_url(content: dict[str, object]) -> str:
    for key in ("canonicalUrl", "clickThroughUrl"):
        candidate = content.get(key)
        if isinstance(candidate, dict):
            url = candidate.get("url")
            if isinstance(url, str) and url:
                return url
    link = content.get("link")
    return link if isinstance(link, str) else ""


def _extract_published(content: dict[str, object]) -> str:
    pub_date = content.get("pubDate")
    if isinstance(pub_date, str) and pub_date:
        try:
            parsed = datetime.datetime.fromisoformat(pub_date.replace("Z", "+00:00"))
        except ValueError:
            pass
        else:
            return parsed.strftime("%Y-%m-%d %H:%M")
    pub_ts = content.get("providerPublishTime") or content.get("publishedTime")
    if isinstance(pub_ts, (int, float)) and not isinstance(pub_ts, bool):
        return datetime.datetime.fromtimestamp(pub_ts, tz=datetime.UTC).strftime("%Y-%m-%d %H:%M")
    return ""


def _fetch_raw_news(jt: str) -> list[dict[str, object]]:
    """yfinance からニュースを取得する。例外・遮断応答はどちらも `NewsFetchError` にする."""
    yf_logger = logging.getLogger("yfinance")
    # `logging.config.fileConfig`（Alembic の env.py 等）は既定で既存ロガーを無効化し、無効化された
    # ロガーは handler を一切呼ばないため検知が黙って効かなくなる。再有効化の副作用は yfinance の
    # ERROR ログが出力されるようになることだけなので、戻さずに有効のままにする。
    yf_logger.disabled = False
    detector = _NewsFailureDetector()
    yf_logger.addHandler(detector)
    try:
        raw_news: list[dict[str, object]] = yf.Ticker(jt).news or []
    except Exception as e:
        raise NewsFetchError(f"{jt}: {e}") from e
    finally:
        yf_logger.removeHandler(detector)
    if detector.detected:
        raise NewsFetchError(f"{jt}: Yahoo がニュース要求を拒否しました（非 JSON 応答）")
    return raw_news


def get_news_sentiment(ticker: str, max_items: int = 20, *, strict: bool = False) -> SentimentSummaryDict:
    """指定銘柄のニュースセンチメントを分析する（1 日キャッシュ、取得失敗はキャッシュしない）.

    `strict=False`（既定、ピック生成・UI）は取得失敗を中立（ニュース 0 件扱い）へ畳んで止めない。
    `strict=True`（PIT 収集）は `NewsFetchError` を送出し、失敗を 0 件として記録させない。
    """
    jt = ticker if ticker.endswith(".T") else f"{ticker}.T"
    cache_key = f"sentiment_{jt}_{max_items}"

    cached = stock_cache.get_json(cache_key)
    if cached is not None:
        logger.info("センチメントキャッシュヒット: %s", jt)
        return cast("SentimentSummaryDict", cached)

    try:
        raw_news = _fetch_raw_news(jt)
    except NewsFetchError as e:
        if strict:
            raise
        logger.warning("ニュース取得エラー: %s", e)
        raw_news = []

    news_items: list[NewsItemDict] = []
    pos_count = neg_count = neutral_count = 0
    score_total = 0.0

    for raw_item in raw_news[:max_items]:
        item = _extract_content(raw_item)
        title = item.get("title", "")
        if not isinstance(title, str) or not title:
            continue

        score, label = _score_text(title)

        news_items.append(
            {
                "title": title,
                "source": _extract_source(item),
                "published": _extract_published(item),
                "url": _extract_url(item),
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
