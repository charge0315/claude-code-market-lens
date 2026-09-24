"""レコメンドサービスの検証（サブスコア統合・source_contributions・ML provider）."""

from __future__ import annotations

from typing import cast

import numpy as np
import pandas as pd
import pytest

from backend.services.scoring import recommender as rec
from backend.services.scoring.subscores import compute_fundamental_score, compute_technical_score


def _uptrend_df(n: int = 90) -> pd.DataFrame:
    idx = pd.date_range("2026-01-01", periods=n, freq="B")
    close = pd.Series(np.linspace(100, 140, n), index=idx)
    return pd.DataFrame({"Open": close, "High": close + 1, "Low": close - 1, "Close": close, "Volume": 1_000_000})


def _df_with_recent_golden_cross() -> pd.DataFrame:
    """末尾付近（直近）でゴールデンクロスが発生する系列（下降→末尾で急上昇に転換）."""
    down = list(np.linspace(200, 100, 60))
    up = list(np.linspace(100, 160, 8))
    closes = down + up[1:]
    idx = pd.date_range("2026-01-01", periods=len(closes), freq="B")
    close = pd.Series(closes, index=idx)
    return pd.DataFrame({"Open": close, "High": close + 1, "Low": close - 1, "Close": close, "Volume": 1_000_000})


def _patch_sources(
    monkeypatch: pytest.MonkeyPatch, *, df: pd.DataFrame, fundamental: dict[str, object], sentiment_total: int
) -> None:
    monkeypatch.setattr(rec, "get_stock_data", lambda _t, period="1y": df)
    monkeypatch.setattr(rec, "get_fundamental_data", lambda _t: fundamental)
    monkeypatch.setattr(
        rec,
        "get_news_sentiment",
        lambda _t, max_items=20: {"total": sentiment_total, "average_score": 0.7 if sentiment_total else 0.5},
    )


def test_subscores_are_bounded_0_100() -> None:
    tech, _ = compute_technical_score(_uptrend_df())
    fund, details = compute_fundamental_score({"per": 8.0, "pbr": 0.7, "roe": 0.25, "dividend_yield": 0.04})
    assert 0.0 <= tech <= 100.0
    assert fund > 50.0  # 割安 × 高収益 → 中立超え
    assert details["value_trap"] is False


def test_value_trap_penalized() -> None:
    _, details = compute_fundamental_score({"roe": -0.05, "pbr": 4.0})
    assert details["value_trap"] is True


def test_technical_signals_has_no_recent_cross_event_when_none_within_lookback() -> None:
    _, details = compute_technical_score(_uptrend_df())
    assert details["recent_cross_event"] is None


def test_technical_signals_includes_recent_cross_event_within_lookback_window() -> None:
    _, details = compute_technical_score(_df_with_recent_golden_cross())
    recent = details["recent_cross_event"]
    assert isinstance(recent, dict)
    assert recent["kind"] == "golden_cross"
    assert recent["days_ago"] <= 10


def test_recommendation_includes_three_value_free_fields_and_contributions(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_sources(
        monkeypatch,
        df=_uptrend_df(),
        fundamental={"per": 9.0, "pbr": 0.8, "roe": 0.22, "dividend_yield": 0.035, "company_name": "テスト"},
        sentiment_total=5,
    )
    out = rec.compute_recommendation("7203")
    assert out["recommendation"] in ("BUY", "HOLD", "SELL")
    composite = cast("float", out["composite_score"])
    assert 0.0 <= composite <= 100.0
    assert out["direction"] in ("bullish", "bearish", "neutral", "mixed")

    contribs = cast("dict[str, dict[str, float]]", out["source_contributions"])
    assert set(contribs).issubset({"technical", "ml_prediction", "fundamental", "sentiment"})
    # ML provider 既定は None なので ml_prediction は寄与に含まれない。
    assert "ml_prediction" not in contribs
    # weight_share は再正規化されて合計 1.0。
    assert sum(c["weight_share"] for c in contribs.values()) == pytest.approx(1.0, abs=1e-3)
    # contribution の合計 ≈ composite。
    assert sum(c["contribution"] for c in contribs.values()) == pytest.approx(composite, abs=0.2)


def test_ml_provider_adds_ml_factor(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_sources(monkeypatch, df=_uptrend_df(), fundamental={"per": 20.0}, sentiment_total=0)

    def ml(_df: pd.DataFrame, _t: str) -> tuple[float | None, float | None]:
        return 90.0, 0.03

    out = rec.compute_recommendation("7203", ml_score_provider=ml)
    breakdown = cast("dict[str, float | None]", out["score_breakdown"])
    assert breakdown["ml_prediction"] == 90.0
    assert "ml_prediction" in cast("dict[str, object]", out["source_contributions"])
    assert out["ml_prediction_rate"] == 0.03
    assert any("ML 予測" in r for r in cast("list[str]", out["reasoning"]))


def test_sentiment_zero_articles_excluded_from_composite(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_sources(monkeypatch, df=_uptrend_df(), fundamental={"per": 15.0}, sentiment_total=0)
    out = rec.compute_recommendation("7203")
    assert cast("dict[str, float | None]", out["score_breakdown"])["sentiment"] is None
    assert "sentiment" not in cast("dict[str, object]", out["source_contributions"])


def test_recent_cross_event_flows_into_technical_signals_and_reasoning(monkeypatch: pytest.MonkeyPatch) -> None:
    """チャート（`/api/stock/{symbol}/ohlc`）のGC/DCマーカーと同じ検出結果がLLMの判断材料
    （`technical_signals`）と人間向け根拠（`reasoning`）の両方に反映されることを確認する（🆕）."""
    _patch_sources(
        monkeypatch,
        df=_df_with_recent_golden_cross(),
        fundamental={"per": 15.0},
        sentiment_total=0,
    )
    out = rec.compute_recommendation("7203")

    signals = cast("dict[str, object]", out["technical_signals"])
    recent = cast("dict[str, object]", signals["recent_cross_event"])
    assert recent["kind"] == "golden_cross"

    assert any("ゴールデンクロス" in r for r in cast("list[str]", out["reasoning"]))


def test_custom_thresholds_change_recommendation(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_sources(monkeypatch, df=_uptrend_df(), fundamental={"per": 15.0}, sentiment_total=0)
    strict = rec.RecommenderThresholds(buy=99.0, sell=1.0)
    out = rec.compute_recommendation("7203", thresholds=strict)
    assert out["recommendation"] == "HOLD"  # buy 閾値 99 には届かない


# --- 🆕 リプレイ学習（P37）: 入力注入版 `recommend_from_inputs` ---


def test_compute_recommendation_matches_recommend_from_inputs(monkeypatch: pytest.MonkeyPatch) -> None:
    """本番経路（取得込み）と入力注入版が同じ入力に対して同一結果を返す（本番挙動を変えない）."""
    df = _uptrend_df()
    fundamental: dict[str, object] = {"per": 9.0, "pbr": 0.8, "roe": 0.22, "company_name": "テスト"}
    _patch_sources(monkeypatch, df=df, fundamental=fundamental, sentiment_total=5)

    via_fetch = rec.compute_recommendation("7203")
    via_inputs = rec.recommend_from_inputs(
        "7203", df=df, fundamental=fundamental, sentiment={"total": 5, "average_score": 0.7}
    )

    assert via_fetch == via_inputs


def test_recommend_from_inputs_excludes_missing_fundamental_and_sentiment() -> None:
    """過去時点で入手できない情報（None）は中立 50 で埋めず、合成スコアから除外して再正規化する."""
    out = rec.recommend_from_inputs("7203", df=_uptrend_df(), fundamental=None, sentiment=None)

    breakdown = cast("dict[str, object]", out["score_breakdown"])
    assert breakdown["fundamental"] is None
    assert breakdown["sentiment"] is None
    contributions = cast("dict[str, object]", out["source_contributions"])
    assert set(contributions) == {"technical"}
    tech = cast("float", breakdown["technical"])
    assert out["composite_score"] == pytest.approx(tech, abs=0.1)
