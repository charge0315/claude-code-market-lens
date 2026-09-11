"""pool_labeling（断面ランクラベルの純関数）のテスト.

ネットワーク・DB・学習済みモデルを一切使わない統計計算だけの単体テスト。
Market Lens `backend/tests/test_pool_labeling.py` から移植（変更なし）。
"""

from __future__ import annotations

import math

from backend.services.learning.pool_labeling import (
    POOL_HORIZON_DAYS,
    POOL_TOP_FRACTION,
    cross_sectional_label,
)


def _returns(n: int) -> dict[str, float]:
    """r_000=0.00, r_001=0.01, ... と単調増加する n 銘柄の前方リターン."""
    return {f"{i:04d}": i * 0.01 for i in range(n)}


def test_constants_are_pinned() -> None:
    assert POOL_HORIZON_DAYS == 10
    assert POOL_TOP_FRACTION == 0.2


def test_top_fraction_gets_label_one() -> None:
    """単調増加リターン100銘柄なら、上位20%（パーセンタイル>=0.8）が label=1."""
    labels = cross_sectional_label(_returns(100))

    assert len(labels) == 100
    positives = {code for code, v in labels.items() if v == 1.0}
    assert positives == {f"{i:04d}" for i in range(80, 100)}
    assert all(labels[f"{i:04d}"] == 0.0 for i in range(80))


def test_non_finite_forward_returns_are_excluded_from_output() -> None:
    data: dict[str, float | None] = _returns(30)  # type: ignore[assignment]
    data["9001"] = None
    data["9002"] = float("nan")

    labels = cross_sectional_label(data)

    assert "9001" not in labels
    assert "9002" not in labels
    assert len(labels) == 30


def test_returns_empty_when_universe_too_small() -> None:
    assert cross_sectional_label(_returns(19)) == {}
    assert cross_sectional_label(_returns(20)) != {}


def test_ties_use_average_rank() -> None:
    """全銘柄同一リターンなら全員パーセンタイル 0.5 未満扱いで label=0（上位に入らない）."""
    labels = cross_sectional_label({f"{i:04d}": 0.05 for i in range(50)})

    assert set(labels.values()) == {0.0}


def test_positive_fraction_is_close_to_top_fraction() -> None:
    labels = cross_sectional_label(_returns(200))
    pos_rate = sum(labels.values()) / len(labels)
    assert math.isclose(pos_rate, POOL_TOP_FRACTION, abs_tol=0.02)
