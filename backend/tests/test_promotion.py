"""昇格ゲート（champion/challenger 判定）の検証（N1）."""

from __future__ import annotations

from pathlib import Path

import pytest

from backend.models.pick import LedgerEntry, SubScores
from backend.services.db import model_registry_db, pick_outcome_db
from backend.services.ledger import prediction_ledger as pl
from backend.services.registry import model_registry as mr
from backend.services.registry import promotion


async def _seed_model(
    version: str, *, n: int, win_rate: float, confidence: float = 70.0, r_multiple_sign: float = 1.0
) -> None:
    """指定バージョンが生成したことにして、決着済みピックを n 件仕込む."""
    n_wins = round(n * win_rate)
    for i in range(n):
        pick_id = f"{version}-{i}"
        win = i < n_wins
        await pl.insert_pick(
            LedgerEntry(
                pick_id=pick_id,
                run_id="r1",
                issued_at=f"2026-{3 + (i % 4):02d}-{(i % 27) + 1:02d}T08:50:00+09:00",
                horizon_type="mid_term",
                symbol=f"{7000 + i}",
                direction="bullish",
                entry=1000.0,
                stop=950.0,
                target=1100.0,
                sub_scores=SubScores(technical=60, trend=55, fundamental=52, sentiment=50),
                composite_score=60.0,
                concordance=0.6,
                confidence_raw=confidence,
                confidence=confidence,
                confidence_bucket=pl.confidence_bucket(confidence),
                feature_snapshot={},
                rationale_struct={},
                rationale_text="x",
                model_version=version,
                source_contributions={},
                created_at="2026-03-01T08:50:01+09:00",
            )
        )
        realized = 0.03 * r_multiple_sign if win else -0.02 * r_multiple_sign
        await pick_outcome_db.upsert_outcome(
            pick_id=pick_id,
            horizon_days=20,
            resolved_at="2026-05-01T16:38:00+09:00",
            realized_return=realized,
            win=win,
            hit_stop=not win,
            hit_target=win,
            first_hit="target" if win else "stop",
            mfe=0.03,
            mae=-0.02,
            benchmark_return=0.0,
            excess_return=realized,
            confidence_bucket=pl.confidence_bucket(confidence),
            direction="bullish",
        )


async def test_compute_model_metrics_empty_when_no_data(migrated_db: Path) -> None:
    metrics = await promotion.compute_model_metrics("nope", horizon_days=20)
    assert metrics.sample_n == 0
    assert metrics.win_rate is None
    assert metrics.paper_days == 0


async def test_evaluate_promotion_holds_when_no_champion(migrated_db: Path) -> None:
    await mr.ensure_registered("v1", lane="mid_term")
    await _seed_model("v1", n=25, win_rate=0.6)

    out = await promotion.evaluate_promotion("mid_term", "v1", horizon_days=20)
    assert out["verdict"] == "hold"

    stored = await model_registry_db.list_promotions(lane="mid_term")
    assert len(stored) == 1 and stored[0]["applied"] == 0


async def test_evaluate_promotion_proposes_when_challenger_beats_champion(migrated_db: Path) -> None:
    await mr.ensure_registered("champ", lane="mid_term")
    await mr.ensure_registered("chal", lane="mid_term")
    await mr.bootstrap_champion_if_missing("mid_term", "champ")

    await _seed_model("champ", n=25, win_rate=0.40)
    await _seed_model("chal", n=25, win_rate=0.70)

    out = await promotion.evaluate_promotion("mid_term", "chal", horizon_days=20)
    assert out["verdict"] == "propose_promote"
    rationale = out["rationale"]
    assert isinstance(rationale, dict) and rationale["champion_version"] == "champ"


async def test_evaluate_promotion_rejects_when_challenger_worse(migrated_db: Path) -> None:
    await mr.ensure_registered("champ", lane="mid_term")
    await mr.ensure_registered("chal", lane="mid_term")
    await mr.bootstrap_champion_if_missing("mid_term", "champ")

    await _seed_model("champ", n=25, win_rate=0.70)
    await _seed_model("chal", n=25, win_rate=0.30)

    out = await promotion.evaluate_promotion("mid_term", "chal", horizon_days=20)
    assert out["verdict"] == "reject"


async def test_evaluate_promotion_compares_champion_only_on_challenger_dates(migrated_db: Path) -> None:
    """挑戦者が後から並走を始めても、champion は挑戦者と同じ発行日の成績だけで比べる.

    champion の過去（挑戦者が存在しなかった期間）が好成績でも、同じ日の比較で挑戦者が勝っていれば
    昇格を提案する（期間のずれで相場環境の差を拾わないため）。
    """
    await mr.ensure_registered("champ", lane="mid_term")
    await mr.ensure_registered("chal", lane="mid_term")
    await mr.bootstrap_champion_if_missing("mid_term", "champ")

    await _seed_model("champ", n=100, win_rate=0.90)  # 3〜6 月の全期間（挑戦者のいない日を含む）
    await _seed_model("chal", n=25, win_rate=0.70)  # 3〜6 月の 25 日分だけ
    # 挑戦者と同じ 25 日の champion は負け越し（champ-0..24 は前半が勝ちになるので、ここで上書き）
    for i in range(25):
        await pick_outcome_db.upsert_outcome(
            pick_id=f"champ-{i}",
            horizon_days=20,
            resolved_at="2026-05-01T16:38:00+09:00",
            realized_return=-0.02,
            win=False,
            hit_stop=True,
            hit_target=False,
            first_hit="stop",
            mfe=0.0,
            mae=-0.02,
            benchmark_return=0.0,
            excess_return=-0.02,
            confidence_bucket="high",
            direction="bullish",
        )

    out = await promotion.evaluate_promotion("mid_term", "chal", horizon_days=20)

    assert out["verdict"] == "propose_promote"
    rationale = out["rationale"]
    assert isinstance(rationale, dict)
    champion_metrics = rationale["champion_metrics"]
    assert isinstance(champion_metrics, dict) and champion_metrics["paper_days"] == 25


async def test_evaluate_promotion_holds_when_paper_days_insufficient(migrated_db: Path) -> None:
    await mr.ensure_registered("champ", lane="mid_term")
    await mr.ensure_registered("chal", lane="mid_term")
    await mr.bootstrap_champion_if_missing("mid_term", "champ")

    await _seed_model("champ", n=25, win_rate=0.40)
    await _seed_model("chal", n=5, win_rate=0.90)  # 好成績だがペーパー日数が基準未満

    out = await promotion.evaluate_promotion("mid_term", "chal", horizon_days=20)
    assert out["verdict"] == "hold"
    rationale = out["rationale"]
    assert isinstance(rationale, dict) and "ペーパー日数" in str(rationale["reason"])


async def test_apply_promotion_switches_champion_only_for_propose_promote(migrated_db: Path) -> None:
    await mr.ensure_registered("champ", lane="mid_term")
    await mr.ensure_registered("chal", lane="mid_term")
    await mr.bootstrap_champion_if_missing("mid_term", "champ")
    await _seed_model("champ", n=25, win_rate=0.40)
    await _seed_model("chal", n=25, win_rate=0.70)

    out = await promotion.evaluate_promotion("mid_term", "chal", horizon_days=20)
    promotion_id = str(out["promotion_id"])

    applied = await promotion.apply_promotion(promotion_id)
    assert applied is True
    assert await model_registry_db.get_champion("mid_term") == "chal"

    # 二重適用は拒否される。
    assert await promotion.apply_promotion(promotion_id) is False


async def test_apply_promotion_refuses_non_propose_verdict(migrated_db: Path) -> None:
    await mr.ensure_registered("champ", lane="mid_term")
    await mr.ensure_registered("chal", lane="mid_term")
    await mr.bootstrap_champion_if_missing("mid_term", "champ")
    await _seed_model("champ", n=25, win_rate=0.70)
    await _seed_model("chal", n=25, win_rate=0.30)

    out = await promotion.evaluate_promotion("mid_term", "chal", horizon_days=20)
    assert out["verdict"] == "reject"
    assert await promotion.apply_promotion(str(out["promotion_id"])) is False
    assert await model_registry_db.get_champion("mid_term") == "champ"


async def test_apply_promotion_unknown_id_returns_false(migrated_db: Path) -> None:
    assert await promotion.apply_promotion("does-not-exist") is False


async def test_evaluate_all_challengers_skips_champion_itself(migrated_db: Path) -> None:
    await mr.ensure_registered("champ", lane="mid_term")
    await mr.bootstrap_champion_if_missing("mid_term", "champ")
    await _seed_model("champ", n=25, win_rate=0.5)

    results = await promotion.evaluate_all_challengers()
    assert "mid_term:champ" not in results


# ---------------------------------------------------------------------------
# lane="ml_pool"（held-out AUC/Brier ベースの昇格判定、ピック実測は使わない）
# ---------------------------------------------------------------------------


async def test_evaluate_ml_pool_promotion_holds_when_no_champion(migrated_db: Path) -> None:
    await mr.ensure_registered("pool-v1", lane="ml_pool", val_metrics={"auc": 0.6, "brier": 0.2})

    out = await promotion.evaluate_ml_pool_promotion("pool-v1")

    assert out["verdict"] == "hold"
    stored = await model_registry_db.list_promotions(lane="ml_pool")
    assert len(stored) == 1 and stored[0]["applied"] == 0


async def test_evaluate_ml_pool_promotion_proposes_when_auc_improves(migrated_db: Path) -> None:
    await mr.ensure_registered("pool-champ", lane="ml_pool", val_metrics={"auc": 0.55, "brier": 0.22})
    await mr.bootstrap_champion_if_missing("ml_pool", "pool-champ")
    await mr.ensure_registered("pool-chal", lane="ml_pool", val_metrics={"auc": 0.65, "brier": 0.20})

    out = await promotion.evaluate_ml_pool_promotion("pool-chal")

    assert out["verdict"] == "propose_promote"
    rationale = out["rationale"]
    assert isinstance(rationale, dict) and rationale["champion_version"] == "pool-champ"


async def test_evaluate_ml_pool_promotion_rejects_when_auc_worse(migrated_db: Path) -> None:
    await mr.ensure_registered("pool-champ", lane="ml_pool", val_metrics={"auc": 0.65, "brier": 0.20})
    await mr.bootstrap_champion_if_missing("ml_pool", "pool-champ")
    await mr.ensure_registered("pool-chal", lane="ml_pool", val_metrics={"auc": 0.55, "brier": 0.20})

    out = await promotion.evaluate_ml_pool_promotion("pool-chal")

    assert out["verdict"] == "reject"


async def test_evaluate_ml_pool_promotion_holds_when_brier_regresses(migrated_db: Path) -> None:
    await mr.ensure_registered("pool-champ", lane="ml_pool", val_metrics={"auc": 0.55, "brier": 0.10})
    await mr.bootstrap_champion_if_missing("ml_pool", "pool-champ")
    # AUC は上回るが Brier が大きく悪化 → hold
    await mr.ensure_registered("pool-chal", lane="ml_pool", val_metrics={"auc": 0.65, "brier": 0.50})

    out = await promotion.evaluate_ml_pool_promotion("pool-chal")

    assert out["verdict"] == "hold"


async def test_evaluate_ml_pool_promotion_unknown_version_raises(migrated_db: Path) -> None:
    with pytest.raises(ValueError, match="未登録"):
        await promotion.evaluate_ml_pool_promotion("does-not-exist")


async def test_apply_ml_pool_promotion_switches_champion(migrated_db: Path) -> None:
    await mr.ensure_registered("pool-champ", lane="ml_pool", val_metrics={"auc": 0.55, "brier": 0.22})
    await mr.bootstrap_champion_if_missing("ml_pool", "pool-champ")
    await mr.ensure_registered("pool-chal", lane="ml_pool", val_metrics={"auc": 0.65, "brier": 0.20})

    out = await promotion.evaluate_ml_pool_promotion("pool-chal")
    assert await promotion.apply_promotion(str(out["promotion_id"])) is True
    assert await model_registry_db.get_champion("ml_pool") == "pool-chal"


async def test_evaluate_all_challengers_includes_ml_pool_lane(migrated_db: Path) -> None:
    await mr.ensure_registered("pool-champ", lane="ml_pool", val_metrics={"auc": 0.55, "brier": 0.22})
    await mr.bootstrap_champion_if_missing("ml_pool", "pool-champ")
    await mr.ensure_registered("pool-chal", lane="ml_pool", val_metrics={"auc": 0.65, "brier": 0.20})

    results = await promotion.evaluate_all_challengers()

    assert results.get("ml_pool:pool-chal") == "propose_promote"
    assert "ml_pool:pool-champ" not in results
