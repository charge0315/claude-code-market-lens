"""レジストリ API（champion/challenger・昇格ゲート・PSI ドリフト）の検証."""

from __future__ import annotations

from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

from backend.models.pick import LedgerEntry, SubScores
from backend.services.db import drift_db, pick_outcome_db
from backend.services.ledger import prediction_ledger as pl
from backend.services.registry import model_registry as mr


async def test_drift_endpoint_returns_history(migrated_db: Path) -> None:
    await drift_db.insert_drift_snapshot(
        feature_name="score_breakdown.technical",
        psi=0.31,
        baseline_window="2026-06-01~2026-07-01",
        current_window="2026-08-01~2026-09-01",
        drift_flag=True,
    )

    from backend.main import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        res = await client.get("/api/registry/drift?feature=score_breakdown.technical")
    body = res.json()
    assert body["success"] is True
    assert len(body["data"]) == 1
    assert body["data"][0]["drift_flag"] == 1
    assert body["data"][0]["psi"] == 0.31


async def test_champions_endpoint_returns_bootstrapped_lane(migrated_db: Path) -> None:
    await mr.ensure_registered("v1", lane="mid_term")
    await mr.bootstrap_champion_if_missing("mid_term", "v1")

    from backend.main import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        res = await client.get("/api/registry/champions")
    body = res.json()
    assert body["success"] is True
    assert any(c["lane"] == "mid_term" and c["champion_version"] == "v1" for c in body["data"])


async def test_champions_endpoint_excludes_per_ticker_lanes(migrated_db: Path) -> None:
    """銘柄別モデル（P9、`lane=f"{model_type}:{ticker}"`）は一覧から除外される."""
    from backend.services.db import model_registry_db

    await mr.ensure_registered("v1", lane="mid_term")
    await mr.bootstrap_champion_if_missing("mid_term", "v1")
    await model_registry_db.upsert_model(version="pt-1", model_type="xgboost", ticker="7203", objective="regression")
    await model_registry_db.set_champion("xgboost:7203", "pt-1", promoted_by="quality_gate")

    from backend.main import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        res = await client.get("/api/registry/champions")
    lanes = [c["lane"] for c in res.json()["data"]]

    assert "mid_term" in lanes
    assert "xgboost:7203" not in lanes


async def _seed_model(version: str, *, n: int, win_rate: float) -> None:
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
                confidence_raw=70.0,
                confidence=70.0,
                confidence_bucket=pl.confidence_bucket(70.0),
                feature_snapshot={},
                rationale_struct={},
                rationale_text="x",
                model_version=version,
                source_contributions={},
                created_at="2026-03-01T08:50:01+09:00",
            )
        )
        realized = 0.03 if win else -0.02
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
            confidence_bucket=pl.confidence_bucket(70.0),
            direction="bullish",
        )


async def test_evaluate_and_apply_promotion_flow(migrated_db: Path) -> None:
    await mr.ensure_registered("champ", lane="mid_term")
    await mr.ensure_registered("chal", lane="mid_term")
    await mr.bootstrap_champion_if_missing("mid_term", "champ")
    await _seed_model("champ", n=25, win_rate=0.40)
    await _seed_model("chal", n=25, win_rate=0.70)

    from backend.main import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        eval_res = await client.post(
            "/api/registry/promotions/evaluate",
            json={"lane": "mid_term", "challenger_version": "chal", "horizon_days": 20},
        )
        eval_body = eval_res.json()
        assert eval_body["success"] is True
        assert eval_body["data"]["verdict"] == "propose_promote"
        promotion_id = eval_body["data"]["promotion_id"]

        list_res = await client.get("/api/registry/promotions?lane=mid_term")
        assert list_res.json()["data"][0]["promotion_id"] == promotion_id

        apply_res = await client.post(f"/api/registry/promotions/{promotion_id}/apply")
        apply_body = apply_res.json()
        assert apply_body["success"] is True
        assert apply_body["data"]["applied"] is True

        second_apply = await client.post(f"/api/registry/promotions/{promotion_id}/apply")
        assert second_apply.json()["success"] is False


async def test_apply_promotion_unknown_id_returns_failure(migrated_db: Path) -> None:
    from backend.main import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        res = await client.post("/api/registry/promotions/does-not-exist/apply")
    body = res.json()
    assert body["success"] is False


async def test_run_training_invokes_daily_batch_for_requested_model_type(
    migrated_db: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """🆕 モデルラボの学習トリガー: 指定モデルタイプの日次学習バッチを即時実行する."""
    from backend.routers import registry as registry_router_module
    from backend.services.learning.per_ticker_training_service import TrainingBatchSummary

    seen_model_type: str | None = None

    async def fake_run_daily_training_batch(model_type: str) -> TrainingBatchSummary:
        nonlocal seen_model_type
        seen_model_type = model_type
        return TrainingBatchSummary(
            model_type=model_type,
            attempted_today=5,
            trained_this_call=3,
            failed_this_call=0,
            quota_reached=False,
            activated_this_call=2,
        )

    monkeypatch.setattr(registry_router_module, "run_daily_training_batch", fake_run_daily_training_batch)

    from backend.main import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        res = await client.post("/api/registry/training/run", json={"model_type": "xgboost"})

    assert seen_model_type == "xgboost"
    body = res.json()
    assert body["success"] is True
    assert body["data"] == {
        "model_type": "xgboost",
        "attempted_today": 5,
        "trained_this_call": 3,
        "failed_this_call": 0,
        "quota_reached": False,
        "activated_this_call": 2,
    }


async def test_run_training_rejects_unknown_model_type(migrated_db: Path) -> None:
    from backend.main import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        res = await client.post("/api/registry/training/run", json={"model_type": "not-a-model"})

    assert res.status_code == 422


async def test_evaluate_promotion_routes_ml_pool_lane_to_holdout_gate(migrated_db: Path) -> None:
    """lane="ml_pool" は held-out AUC/Brier ゲート（`evaluate_ml_pool_promotion`）へ分岐する."""
    await mr.ensure_registered("pool-champ", lane="ml_pool", val_metrics={"auc": 0.55, "brier": 0.22})
    await mr.bootstrap_champion_if_missing("ml_pool", "pool-champ")
    await mr.ensure_registered("pool-chal", lane="ml_pool", val_metrics={"auc": 0.65, "brier": 0.20})

    from backend.main import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        res = await client.post(
            "/api/registry/promotions/evaluate", json={"lane": "ml_pool", "challenger_version": "pool-chal"}
        )
    body = res.json()
    assert body["success"] is True
    assert body["data"]["verdict"] == "propose_promote"
