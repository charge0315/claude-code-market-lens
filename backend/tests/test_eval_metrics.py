"""評価指標の純関数の検証（Market Lens から移植 + Alpha Forge 追加分）."""

from __future__ import annotations

import math

import pytest

from backend.services.ledger import eval_metrics as em


def test_spearman_ic_monotonic() -> None:
    scores = [1, 2, 3, 4, 5]
    fwd = [0.01, 0.02, 0.015, 0.04, 0.05]  # 概ね単調増
    ic = em.spearman_ic(scores, fwd)
    assert ic is not None and ic > 0.8
    assert em.spearman_ic([1, 2], [0.1, 0.2]) is None  # サンプル不足


def test_precision_at_k() -> None:
    scores = [10, 9, 8, 7, 6]
    wins = [1, 1, 0, 0, 1]
    assert em.precision_at_k(scores, wins, 2) == 1.0  # 上位 2 件は勝ち
    assert em.precision_at_k(scores, wins, 5) == pytest.approx(0.6)
    assert em.precision_at_k(scores, wins, 9) is None


def test_calibration_table_buckets() -> None:
    labels = [0, 0, 1, 1, 1, 1]
    probs = [0.1, 0.2, 0.6, 0.7, 0.8, 0.9]
    rows = em.calibration_table(labels, probs, n_buckets=5)
    assert rows
    # 低確率バケットは実測勝率が低い、高確率バケットは高い。
    assert rows[0][2] < rows[-1][2]


def test_evaluate_classification_brier_skill() -> None:
    labels = [0, 1, 0, 1, 1, 0, 1, 0]
    probs = [0.2, 0.8, 0.3, 0.7, 0.9, 0.1, 0.6, 0.4]
    est = em.evaluate_classification(labels, probs)
    assert est is not None
    assert est.auc is not None and est.auc > 0.9
    assert est.brier_skill > 0.0  # base より良い


def test_evaluate_predictions_skill_ci() -> None:
    predicted = [0.01, 0.02, 0.03, 0.015, 0.025, 0.005]
    actual = [0.012, 0.018, 0.028, 0.02, 0.022, 0.008]
    est = em.evaluate_predictions(predicted, actual, bootstrap_iterations=200)
    assert est is not None
    assert est.skill > 0.0  # ナイーブ（全 0 予測）より良い
    assert est.skill_ci_lower <= est.skill <= est.skill_ci_upper


def test_equity_curve_and_drawdown_and_sharpe() -> None:
    returns = [0.1, -0.05, 0.2, -0.1]
    eq = em.equity_curve(returns)
    assert eq[0] == pytest.approx(1.1)
    assert len(eq) == 4
    dd = em.max_drawdown(eq)
    assert dd > 0.0
    sr = em.sharpe_ratio(returns)
    assert sr is not None and math.isfinite(sr)
    assert em.sharpe_ratio([0.01]) is None


def test_decile_return_spread() -> None:
    scores = list(range(20))
    returns = [s * 0.001 for s in scores]  # スコアとリターンが完全連動
    ds = em.decile_return_spread(scores, returns, n_deciles=5)
    assert ds is not None and ds.spread > 0
