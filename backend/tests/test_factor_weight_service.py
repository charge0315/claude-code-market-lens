"""factor_weight_service（ファクター実測 IC の算出、shadow モード）のテスト.

`prediction_ledger` + `pick_outcomes` へ直接シードし、|IC| 比例の重み算出ロジックを検証する
（Market Lens 版は別テーブル `signal_scan_ic_runs` をモックしていたが、Alpha Forge 版は
既存の決着済みピックから直接算出するため実データを積む）。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from backend.models.pick import LedgerEntry, SubScores
from backend.services.db import pick_outcome_db
from backend.services.ledger import prediction_ledger as pl
from backend.services.registry import factor_weight_service as svc
from backend.services.scoring.recommender import FACTOR_WEIGHTS


async def _seed_pick(pick_id: str, *, factor_scores: dict[str, float], excess_return: float, win: bool = True) -> None:
    source_contributions = {
        factor: {"weight_share": 0.25, "contribution": score * 0.25, "score": score}
        for factor, score in factor_scores.items()
    }
    await pl.insert_pick(
        LedgerEntry(
            pick_id=pick_id,
            run_id="r1",
            issued_at="2026-03-01T08:50:00+09:00",
            horizon_type="mid_term",
            symbol="7203",
            direction="bullish",
            entry=1000.0,
            stop=950.0,
            target=1100.0,
            sub_scores=SubScores(technical=60, trend=55, fundamental=52, sentiment=50),
            composite_score=60.0,
            concordance=0.6,
            confidence_raw=70.0,
            confidence=70.0,
            confidence_bucket=pl.confidence_bucket(70.0),
            feature_snapshot={},
            rationale_struct={},
            rationale_text="x",
            model_version="v1",
            source_contributions=source_contributions,
            created_at="2026-03-01T08:50:01+09:00",
        )
    )
    await pick_outcome_db.upsert_outcome(
        pick_id=pick_id,
        horizon_days=20,
        resolved_at="2026-04-01T16:38:00+09:00",
        realized_return=excess_return,
        win=win,
        hit_stop=not win,
        hit_target=win,
        first_hit="target" if win else "stop",
        mfe=0.03,
        mae=-0.02,
        benchmark_return=0.0,
        excess_return=excess_return,
        confidence_bucket=pl.confidence_bucket(70.0),
        direction="bullish",
    )


async def test_falls_back_to_default_weights_when_no_resolved_picks(migrated_db: Path) -> None:
    """決着済みピックが無ければ、全ファクターが FACTOR_WEIGHTS と同じ比率になる（初期状態）."""
    weights = await svc.compute_ic_weights(horizon_days=20)

    assert set(weights.keys()) == set(FACTOR_WEIGHTS.keys())
    total_default = sum(FACTOR_WEIGHTS.values())
    for factor, default in FACTOR_WEIGHTS.items():
        assert weights[factor] == pytest.approx(default / total_default, abs=1e-3)


async def test_weights_sum_to_one(migrated_db: Path) -> None:
    for i in range(25):
        await _seed_pick(f"p{i}", factor_scores={"technical": 50.0 + i}, excess_return=0.001 * i)

    weights = await svc.compute_ic_weights(horizon_days=20)
    assert sum(weights.values()) == pytest.approx(1.0, abs=1e-3)


async def test_higher_abs_ic_gets_higher_weight(migrated_db: Path) -> None:
    """technical のスコアは実現超過リターンとほぼ完全に順位相関する一方、fundamental は
    ノイズ交じりの中程度の相関 — |IC| が大きいファクターほど重みが大きくなること.

    sentiment はあえて未シード（既定重みへフォールバック）にする — 極端に |IC|=0 に近い
    ファクターを混ぜると `_normalize_with_ratio_clip` の比率クリップが technical/fundamental
    両方を同じ上限へ押し込め、差が潰れてしまうため（クリップは最小値の何倍までという相対
    仕様であり、最小値そのものが実測ゼロ近傍だと他ファクターの差を吸収してしまう）。
    """
    import random

    rng = random.Random(0)
    for i in range(30):
        await _seed_pick(
            f"p{i}",
            factor_scores={
                "technical": 50.0 + i,  # 完全な正の順位相関
                "fundamental": 50.0 - i * 0.3 + rng.uniform(-8.0, 8.0),  # ノイズ交じりの中程度の相関
            },
            excess_return=0.001 * i,
        )

    weights = await svc.compute_ic_weights(horizon_days=20)
    assert weights["technical"] > weights["fundamental"]


async def test_low_sample_count_falls_back_to_default(migrated_db: Path) -> None:
    """サンプル数が閾値未満のファクターは信頼性が薄いため既定重みへフォールバックする."""
    for i in range(5):  # _MIN_SAMPLES_FOR_IC=20 未満
        await _seed_pick(f"p{i}", factor_scores={"technical": 50.0 + i * 10}, excess_return=0.01 * i)

    weights = await svc.compute_ic_weights(horizon_days=20)
    total_default = sum(FACTOR_WEIGHTS.values())
    assert weights["technical"] == pytest.approx(FACTOR_WEIGHTS["technical"] / total_default, abs=1e-3)


async def test_missing_factor_contribution_does_not_crash_and_still_normalizes(migrated_db: Path) -> None:
    """ml_prediction の寄与が皆無のピックしか無くても例外にならず、有効な重み（合計1.0）を返す
    （その IC 算出対象が空になり `_MIN_SAMPLES_FOR_IC` 未満で既定重みへフォールバックするだけ）."""
    for i in range(25):
        await _seed_pick(f"p{i}", factor_scores={"technical": 50.0 + i}, excess_return=0.001 * i)

    weights = await svc.compute_ic_weights(horizon_days=20)
    assert set(weights.keys()) == set(FACTOR_WEIGHTS.keys())
    assert sum(weights.values()) == pytest.approx(1.0, abs=1e-3)
    assert all(w > 0 for w in weights.values())


async def test_default_horizon_is_the_longer_one() -> None:
    """デフォルト horizon は保有期間の目安に近い長い方（20営業日）を使う."""
    assert svc.DEFAULT_HORIZON_DAYS == 20


def test_ic_weights_from_rows_accepts_parsed_contributions() -> None:
    """🆕 P37: リプレイ台帳（JSON 解析済み dict）からも同じ規則で IC 重みを出せる純関数."""
    rows: list[dict[str, object]] = [
        {"source_contributions": {"technical": {"score": float(i)}}, "excess_return": i / 100.0} for i in range(30)
    ]

    weights = svc.ic_weights_from_rows(rows)

    assert set(weights) == set(svc.FACTOR_WEIGHTS)
    assert sum(weights.values()) == pytest.approx(1.0, abs=1e-3)
    # technical の |IC| = 1.0（完全順位相関）が既定重みより大きいので最大の重みになる
    assert max(weights, key=lambda k: weights[k]) == "technical"


def test_ic_weights_from_rows_can_restrict_factors() -> None:
    """🆕 P37: 対象ファクターを絞ると、その集合だけで正規化する（入力の無いファクターへ既定重みを残さない）."""
    rows: list[dict[str, object]] = [
        {
            "source_contributions": {"technical": {"score": float(i)}, "ml_prediction": {"score": 30.0 - i}},
            "excess_return": i / 100.0,
        }
        for i in range(30)
    ]

    weights = svc.ic_weights_from_rows(rows, factors=("technical", "ml_prediction"))

    assert set(weights) == {"technical", "ml_prediction"}
    assert sum(weights.values()) == pytest.approx(1.0, abs=1e-3)
