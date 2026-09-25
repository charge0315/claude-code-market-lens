"""ニュースセンチメント分析の検証（Market Lens から移植）."""

from __future__ import annotations

import logging
import threading

import pytest

from backend.services.scoring import sentiment_analyzer as sa


def test_score_text_positive_negative_neutral() -> None:
    assert sa._score_text("最高値を更新、増益で好調")[1] == "positive"
    assert sa._score_text("暴落で赤字、下方修正の警告")[1] == "negative"
    assert sa._score_text("特に変化なし")[1] == "neutral"


def test_confidence_shrinkage_pulls_toward_neutral_for_few_articles() -> None:
    # raw 1.0、記事 1 件 → confidence 0.1 → 0.5 + 0.5*0.1 = 0.55。
    assert sa._apply_confidence_shrinkage(1.0, 1) == pytest.approx(0.55)
    # 記事 10 件以上なら raw そのまま。
    assert sa._apply_confidence_shrinkage(1.0, 20) == pytest.approx(1.0)


def test_get_news_sentiment_aggregates_and_shrinks(monkeypatch: pytest.MonkeyPatch) -> None:
    # 🔧 yfinance 現行版のネスト形式（`content` 配下）。
    news: list[dict[str, object]] = [
        {
            "content": {
                "title": "増益で急騰、最高値更新",
                "provider": {"displayName": "X"},
                "canonicalUrl": {"url": "u1"},
                "pubDate": "2026-09-18T08:00:00Z",
            }
        },
        {
            "content": {
                "title": "上方修正で買い優勢",
                "provider": {"displayName": "X"},
                "canonicalUrl": {"url": "u2"},
                "pubDate": "2026-09-18T09:00:00Z",
            }
        },
    ]

    class FakeTicker:
        def __init__(self, _s: str) -> None:
            self.news = news

    monkeypatch.setattr(sa.yf, "Ticker", FakeTicker)
    monkeypatch.setattr(sa.stock_cache, "get_json", lambda _k: None)
    monkeypatch.setattr(sa.stock_cache, "set_json", lambda *_a, **_k: None)

    out = sa.get_news_sentiment("7203")
    assert out["total"] == 2
    assert out["positive"] == 2
    # 2 件のみ → confidence 0.2、avg は raw(1.0) から中立寄りに縮小される。
    assert out["confidence"] == pytest.approx(0.2)
    assert 0.5 < out["average_score"] < out["raw_average_score"]
    assert out["news"][0]["source"] == "X"
    assert out["news"][0]["url"] == "u1"
    assert out["news"][0]["published"] == "2026-09-18 08:00"


def test_get_news_sentiment_supports_legacy_flat_format(monkeypatch: pytest.MonkeyPatch) -> None:
    """🔧 旧フラット形式（`content` ネスト無し）も引き続き解釈できること（後方互換）."""
    news: list[dict[str, object]] = [
        {"title": "増益で急騰、最高値更新", "publisher": "X", "link": "u1", "providerPublishTime": 1_760_000_000}
    ]

    class FakeTicker:
        def __init__(self, _s: str) -> None:
            self.news = news

    monkeypatch.setattr(sa.yf, "Ticker", FakeTicker)
    monkeypatch.setattr(sa.stock_cache, "get_json", lambda _k: None)
    monkeypatch.setattr(sa.stock_cache, "set_json", lambda *_a, **_k: None)

    out = sa.get_news_sentiment("7203")
    assert out["total"] == 1
    assert out["news"][0]["source"] == "X"
    assert out["news"][0]["url"] == "u1"


def test_empty_news_returns_neutral_and_is_not_cached(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeTicker:
        def __init__(self, _s: str) -> None:
            self.news: list[dict[str, object]] = []

    saved: list[object] = []
    monkeypatch.setattr(sa.yf, "Ticker", FakeTicker)
    monkeypatch.setattr(sa.stock_cache, "get_json", lambda _k: None)
    monkeypatch.setattr(sa.stock_cache, "set_json", lambda *a, **k: saved.append(a))

    out = sa.get_news_sentiment("9999")
    assert out["total"] == 0
    assert out["average_score"] == 0.5
    assert out["confidence"] == 0.0
    assert saved == []  # 取得失敗はキャッシュしない


def _blocked_ticker_class() -> type:
    """Yahoo が HTTP 999 等で拒否したときの yfinance の挙動（ERROR ログを出して空リストを返す）を再現する."""

    class BlockedTicker:
        def __init__(self, symbol: str) -> None:
            self._symbol = symbol

        @property
        def news(self) -> list[dict[str, object]]:
            logging.getLogger("yfinance").error(
                "%s: Failed to retrieve the news and received faulty response instead.", self._symbol
            )
            return []

    return BlockedTicker


def _disable_cache(monkeypatch: pytest.MonkeyPatch, saved: list[object] | None = None) -> None:
    monkeypatch.setattr(sa.stock_cache, "get_json", lambda _k: None)
    monkeypatch.setattr(sa.stock_cache, "set_json", lambda *a, **k: saved.append(a) if saved is not None else None)


def test_strict_raises_news_fetch_error_when_yahoo_rejects(monkeypatch: pytest.MonkeyPatch) -> None:
    """拒否応答を「ニュース 0 件」と区別し、strict 呼び出しでは例外として呼び出し元へ伝える."""
    monkeypatch.setattr(sa.yf, "Ticker", _blocked_ticker_class())
    _disable_cache(monkeypatch)

    with pytest.raises(sa.NewsFetchError):
        sa.get_news_sentiment("7203", strict=True)


def test_strict_raises_news_fetch_error_when_yfinance_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    class RaisingTicker:
        def __init__(self, _s: str) -> None:
            pass

        @property
        def news(self) -> list[dict[str, object]]:
            raise RuntimeError("*** YAHOO! FINANCE IS CURRENTLY DOWN! ***")

    monkeypatch.setattr(sa.yf, "Ticker", RaisingTicker)
    _disable_cache(monkeypatch)

    with pytest.raises(sa.NewsFetchError):
        sa.get_news_sentiment("7203", strict=True)


def test_non_strict_falls_back_to_neutral_on_rejection(monkeypatch: pytest.MonkeyPatch) -> None:
    """既定（非 strict）の呼び出し元（ピック生成・UI）は従来どおり中立フォールバックで止まらない."""
    saved: list[object] = []
    monkeypatch.setattr(sa.yf, "Ticker", _blocked_ticker_class())
    _disable_cache(monkeypatch, saved)

    out = sa.get_news_sentiment("7203")

    assert out["total"] == 0
    assert out["average_score"] == 0.5
    assert saved == []


def test_rejection_logged_by_other_thread_is_not_attributed(monkeypatch: pytest.MonkeyPatch) -> None:
    """別スレッドの yfinance 失敗ログを自分の取得失敗と誤認しない（FastAPI のスレッド並行呼び出し対策）."""

    class OtherThreadFailsTicker:
        def __init__(self, _s: str) -> None:
            pass

        @property
        def news(self) -> list[dict[str, object]]:
            t = threading.Thread(
                target=lambda: logging.getLogger("yfinance").error(
                    "9999.T: Failed to retrieve the news and received faulty response instead."
                )
            )
            t.start()
            t.join()
            return []

    monkeypatch.setattr(sa.yf, "Ticker", OtherThreadFailsTicker)
    _disable_cache(monkeypatch)

    out = sa.get_news_sentiment("7203", strict=True)

    assert out["total"] == 0


def test_detects_rejection_even_if_yfinance_logger_was_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    """`fileConfig`（Alembic env.py 等）が既存ロガーを無効化しても拒否を検知できること."""
    monkeypatch.setattr(logging.getLogger("yfinance"), "disabled", True)
    monkeypatch.setattr(sa.yf, "Ticker", _blocked_ticker_class())
    _disable_cache(monkeypatch)

    with pytest.raises(sa.NewsFetchError):
        sa.get_news_sentiment("7203", strict=True)
