"""technical_analysis.py のクロスイベント検出（🆕、GC/DC・MACDクロス）のテスト."""

from __future__ import annotations

import numpy as np
import pandas as pd

from backend.services.scoring.technical_analysis import (
    detect_cross_events,
    detect_macd_cross_events,
    detect_sma_cross_events,
)


def _make_df(closes: list[float]) -> pd.DataFrame:
    dates = pd.bdate_range("2026-01-01", periods=len(closes))
    return pd.DataFrame({"Close": closes}, index=dates)


def _down_up_down(n: int = 30) -> list[float]:
    """下降→急上昇（ゴールデンクロス）→急下降（デッドクロス）と転換する合成系列を作る."""
    down = list(np.linspace(200, 100, n))
    up = list(np.linspace(100, 300, n))
    down_again = list(np.linspace(300, 50, n))
    return down + up[1:] + down_again[1:]


def test_detect_sma_cross_events_finds_golden_then_dead_cross() -> None:
    df = _make_df(_down_up_down())

    events = detect_sma_cross_events(df, short=5, long=25)

    kinds = [e["kind"] for e in events]
    assert "golden_cross" in kinds
    assert "dead_cross" in kinds
    assert kinds.index("golden_cross") < kinds.index("dead_cross")
    assert all(e["date"] for e in events)
    assert all(e["label"] for e in events)


def test_detect_sma_cross_events_returns_nothing_when_history_too_short() -> None:
    # SMA25 が全て None（25本未満）のため交差判定自体が発生しない。
    closes = list(np.linspace(100, 101, 20))
    df = _make_df(closes)

    assert detect_sma_cross_events(df) == []


def test_detect_macd_cross_events_finds_bullish_cross_on_sustained_uptrend() -> None:
    down = list(np.linspace(200, 100, 40))
    up = list(np.linspace(100, 300, 40))
    df = _make_df(down + up[1:])

    events = detect_macd_cross_events(df)

    assert any(e["kind"] == "macd_bullish_cross" for e in events)


def test_detect_macd_cross_events_ignores_the_seeded_first_point() -> None:
    """MACD のシグナル線は先頭値がMACD線そのものと一致するため、系列先頭2点は
    比較対象から除外され疑似クロスを生まないことを確認する（回帰防止）。"""
    df = _make_df([1000.0, 1001.0])

    assert detect_macd_cross_events(df) == []


def test_detect_cross_events_merges_sma_and_macd_sorted_by_date() -> None:
    df = _make_df(_down_up_down())

    sma_events = detect_sma_cross_events(df)
    macd_events = detect_macd_cross_events(df)
    merged = detect_cross_events(df)

    assert len(merged) == len(sma_events) + len(macd_events)
    assert [e["date"] for e in merged] == sorted(e["date"] for e in merged)
