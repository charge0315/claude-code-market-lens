"""シグナルスコアリング純関数の検証（Market Lens から移植）."""

from __future__ import annotations

import numpy as np
import pandas as pd

from backend.services.scoring import signal_scan_scoring as sss


def test_compute_composite_renormalizes_available_factors() -> None:
    # technical=60(w0.4), fundamental=40(w0.3), trend 欠損 → (60*0.4+40*0.3)/0.7 = 51.4
    out = sss.compute_composite({"technical": 60.0, "fundamental": 40.0, "trend": None})
    assert out == 51.4
    assert sss.compute_composite({"technical": None, "trend": None, "fundamental": None}) is None


def test_compute_composite_accepts_custom_weights() -> None:
    out = sss.compute_composite(
        {"technical": 80.0, "ml_prediction": 20.0}, weights={"technical": 0.5, "ml_prediction": 0.5}
    )
    assert out == 50.0


def test_compute_concordance_directions() -> None:
    assert sss.compute_concordance({"technical": 70, "trend": 65, "fundamental": 60}) == (1.0, "bullish")
    assert sss.compute_concordance({"technical": 30, "trend": 35, "fundamental": 40}) == (1.0, "bearish")
    assert sss.compute_concordance({"technical": 70, "trend": 30, "fundamental": 50})[1] == "mixed"
    assert sss.compute_concordance({"technical": 50, "trend": 50, "fundamental": 50}) == (0.0, "neutral")


def test_classify_status_and_completeness() -> None:
    full = {"technical": 50, "trend": 50, "fundamental": 50}
    assert sss.classify_status(full) == "ok"
    assert sss.compute_data_completeness(full) == 1.0
    assert sss.classify_status({"technical": 50}) == "partial"
    assert sss.classify_status({}) == "failed"


def test_compute_trend_score_uptrend_scores_above_neutral() -> None:
    idx = pd.date_range("2026-01-01", periods=70, freq="B")
    close = pd.Series(np.linspace(100, 140, 70), index=idx)
    df = pd.DataFrame({"Close": close})
    score, detail = sss.compute_trend_score(df)
    assert score is not None and score > 50
    assert detail["vs_sma50"] == "above"


def test_compute_trend_score_returns_none_on_short_history() -> None:
    df = pd.DataFrame({"Close": [100.0] * 10})
    assert sss.compute_trend_score(df) == (None, {})


def test_histogram_bins_are_fixed_ten() -> None:
    bins = sss.histogram([5, 15, 95, 100])
    assert len(bins) == 10
    assert bins[0][2] == 1  # 0-10
    assert bins[9][2] == 2  # 90-100（100 は最終ビン）


def test_compute_confidence_monotonic_in_inputs() -> None:
    low = sss.compute_confidence(data_completeness=0.3, price_rows=20, fundamental_field_count=1)
    high = sss.compute_confidence(data_completeness=1.0, price_rows=250, fundamental_field_count=4)
    assert 0.0 <= low < high <= 1.0
