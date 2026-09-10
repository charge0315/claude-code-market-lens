"""ニュースセンチメント分析の検証（Market Lens から移植）."""

from __future__ import annotations

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
    news: list[dict[str, object]] = [
        {"title": "増益で急騰、最高値更新", "publisher": "X", "link": "u1", "providerPublishTime": 1_760_000_000},
        {"title": "上方修正で買い優勢", "publisher": "X", "link": "u2", "providerPublishTime": 1_760_000_100},
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
