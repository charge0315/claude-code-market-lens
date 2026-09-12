"""レジストリ API（champion/challenger・昇格ゲート・PSI ドリフト）の検証."""

from __future__ import annotations

import asyncio
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


async def test_run_training_starts_in_background_and_status_reports_completion(
    migrated_db: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """🔧 P13h: 学習バッチはバックグラウンドで起動し即座に応答する（同期 await で数分待たせない）.

    多分間かかりうる学習バッチをリクエスト内で同期 await すると、経路上のどこか
    （Next.js の rewrite プロキシ等）のタイムアウトでブラウザには失敗と映る一方、
    バックエンド側は処理を継続してしまう不整合が実機で発覚したための変更。
    """
    from backend.routers import registry as registry_router_module
    from backend.services.learning.per_ticker_training_service import TrainingBatchSummary

    seen_model_type: str | None = None
    seen_overrides: tuple[int | None, float | None] | None = None
    gate = asyncio.Event()

    async def fake_run_daily_training_batch(
        model_type: str,
        *,
        daily_limit_override: int | None = None,
        max_duration_override: float | None = None,
        on_progress: object = None,  # 🆕 P17: シグネチャ互換のため受け取るが未使用
    ) -> TrainingBatchSummary:
        nonlocal seen_model_type, seen_overrides
        seen_model_type = model_type
        seen_overrides = (daily_limit_override, max_duration_override)
        await gate.wait()  # テストが明示的に解放するまでバックグラウンドタスクを止めておく
        return TrainingBatchSummary(
            model_type=model_type,
            attempted_today=5,
            trained_this_call=3,
            failed_this_call=0,
            quota_reached=False,
            activated_this_call=2,
        )

    monkeypatch.setattr(registry_router_module, "run_daily_training_batch", fake_run_daily_training_batch)
    registry_router_module._running_batches.clear()
    registry_router_module._last_results.clear()

    from backend.main import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        run_res = await client.post("/api/registry/training/run", json={"model_type": "xgboost"})
        assert run_res.json() == {
            "success": True,
            "data": {"model_type": "xgboost", "status": "started"},
            "error": None,
            "meta": None,
        }
        assert seen_model_type == "xgboost"
        # 🆕 P14: 手動トリガーは全銘柄まで学習する override 付きで呼ばれる。
        from backend.services.learning.per_ticker_training_service import manual_full_run_overrides

        assert seen_overrides == manual_full_run_overrides("xgboost")

        # ゲート解放前は実行中のまま（バックグラウンドタスクが gate.wait() で止まっている）。
        running_res = await client.get("/api/registry/training/status?model_type=xgboost")
        assert running_res.json()["data"]["running"] is True
        assert running_res.json()["data"]["last_result"] is None

        task = registry_router_module._running_batches["xgboost"]
        gate.set()
        await task

        status_res = await client.get("/api/registry/training/status?model_type=xgboost")

    status_body = status_res.json()["data"]
    assert status_body["running"] is False
    assert status_body["last_result"] == {
        "model_type": "xgboost",
        "attempted_today": 5,
        "trained_this_call": 3,
        "failed_this_call": 0,
        "quota_reached": False,
        "activated_this_call": 2,
        "error": None,
    }


async def test_training_status_reports_live_progress_while_running(
    migrated_db: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """🆕 P17: 実行中は処理中の銘柄・進捗率・既存比（品質ゲート通過率）等をライブで返す."""
    from backend.routers import registry as registry_router_module
    from backend.services.learning.per_ticker_training_service import TrainingBatchSummary, TrainingProgressEvent

    gate = asyncio.Event()

    async def fake_run_daily_training_batch(
        model_type: str,
        *,
        daily_limit_override: int | None = None,  # noqa: ARG001
        max_duration_override: float | None = None,  # noqa: ARG001
        on_progress: object = None,
    ) -> TrainingBatchSummary:
        assert callable(on_progress)
        on_progress(TrainingProgressEvent(ticker="7203", processed=0, total=2, status="running"))
        on_progress(
            TrainingProgressEvent(
                ticker="7203", processed=1, total=2, status="completed", activated=True, data_source="yfinance"
            )
        )
        on_progress(TrainingProgressEvent(ticker="6758", processed=1, total=2, status="running"))
        await gate.wait()
        return TrainingBatchSummary(
            model_type=model_type, attempted_today=1, trained_this_call=1, failed_this_call=0, quota_reached=False
        )

    monkeypatch.setattr(registry_router_module, "run_daily_training_batch", fake_run_daily_training_batch)
    registry_router_module._running_batches.clear()
    registry_router_module._last_results.clear()
    registry_router_module._progress.clear()

    from backend.main import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        await client.post("/api/registry/training/run", json={"model_type": "xgboost"})
        status_res = await client.get("/api/registry/training/status?model_type=xgboost")

        gate.set()
        await registry_router_module._running_batches["xgboost"]

        idle_res = await client.get("/api/registry/training/status?model_type=xgboost")

    progress = status_res.json()["data"]["progress"]
    assert progress["current_ticker"] == "6758"
    assert progress["processed"] == 1
    assert progress["total"] == 2
    assert progress["promotion_rate_pct"] == 100.0
    assert progress["failed_this_run"] == 0
    assert progress["eta_seconds"] is not None and progress["eta_seconds"] >= 0

    # バッチ終了後は progress がクリアされ、実行中のライブ状態は無くなる。
    assert idle_res.json()["data"]["progress"] is None


async def test_run_training_returns_already_running_when_triggered_twice(
    migrated_db: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from backend.routers import registry as registry_router_module

    gate = asyncio.Event()

    async def fake_run_daily_training_batch(model_type: str, **_kwargs: object) -> object:  # noqa: ARG001
        await gate.wait()
        raise AssertionError("test forces this coroutine to never resolve normally")

    monkeypatch.setattr(registry_router_module, "run_daily_training_batch", fake_run_daily_training_batch)
    registry_router_module._running_batches.clear()
    registry_router_module._last_results.clear()

    from backend.main import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        first = await client.post("/api/registry/training/run", json={"model_type": "lstm"})
        second = await client.post("/api/registry/training/run", json={"model_type": "lstm"})

    assert first.json()["data"]["status"] == "started"
    assert second.json()["data"]["status"] == "already_running"

    # 後片付け: ぶら下がったタスクをキャンセルする。
    gate.set()
    task = registry_router_module._running_batches.pop("lstm", None)
    if task is not None:
        task.cancel()


async def test_training_status_reflects_attempted_tickers_from_db(migrated_db: Path) -> None:
    from backend.services.db.training_batch_db import insert_training_batch_run
    from backend.services.jst_time import today_jst

    await insert_training_batch_run(run_date=today_jst(), ticker="7203", model_type="xgboost", status="completed")
    await insert_training_batch_run(run_date=today_jst(), ticker="6758", model_type="xgboost", status="failed")

    from backend.main import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        res = await client.get("/api/registry/training/status?model_type=xgboost")

    body = res.json()["data"]
    assert body["running"] is False
    assert body["attempted_today"] == 2
    assert body["last_result"] is None


async def test_run_training_rejects_unknown_model_type(migrated_db: Path) -> None:
    from backend.main import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        res = await client.post("/api/registry/training/run", json={"model_type": "not-a-model"})

    assert res.status_code == 422


async def test_training_status_rejects_unknown_model_type(migrated_db: Path) -> None:
    from backend.main import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        res = await client.get("/api/registry/training/status?model_type=not-a-model")

    assert res.status_code == 422


async def test_model_stats_coverage_endpoint_returns_all_model_types(migrated_db: Path) -> None:
    from backend.services.db import model_registry_db

    await model_registry_db.upsert_model(version="v1", model_type="xgboost", ticker="7203", objective="regression")
    await model_registry_db.set_champion("xgboost:7203", "v1", promoted_by="quality_gate")

    from backend.main import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        res = await client.get("/api/registry/model-stats/coverage")

    body = res.json()
    assert body["success"] is True
    by_type = {row["model_type"]: row for row in body["data"]}
    assert set(by_type) == {"xgboost", "random_forest", "lstm", "transformer"}
    assert by_type["xgboost"]["trained_count"] == 1
    assert by_type["xgboost"]["champion_count"] == 1
    assert by_type["lstm"]["trained_count"] == 0


async def test_model_stats_quality_endpoint_returns_champion_metrics(migrated_db: Path) -> None:
    from backend.services.db import model_registry_db

    await model_registry_db.upsert_model(
        version="v1",
        model_type="xgboost",
        ticker="7203",
        objective="regression",
        val_metrics={"skill": 0.4, "rmse": 1.2},
    )
    await model_registry_db.set_champion("xgboost:7203", "v1", promoted_by="quality_gate")

    from backend.main import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        res = await client.get("/api/registry/model-stats/quality")

    body = res.json()
    assert body["success"] is True
    xgb = next(row for row in body["data"] if row["model_type"] == "xgboost")
    assert xgb["skill_scores"] == [0.4]
    assert xgb["rmse_scores"] == [1.2]


async def test_model_stats_training_trend_endpoint_returns_daily_counts(migrated_db: Path) -> None:
    from backend.services.db.training_batch_db import insert_training_batch_run
    from backend.services.jst_time import today_jst

    today = today_jst()
    await insert_training_batch_run(run_date=today, ticker="7203", model_type="xgboost", status="completed")
    await insert_training_batch_run(run_date=today, ticker="6758", model_type="xgboost", status="failed")

    from backend.main import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        res = await client.get("/api/registry/model-stats/training-trend?days=30")

    body = res.json()
    assert body["success"] is True
    point = next(row for row in body["data"] if row["date"] == today and row["model_type"] == "xgboost")
    assert point["trained_count"] == 1
    assert point["failed_count"] == 1


async def test_model_stats_training_trend_rejects_invalid_days(migrated_db: Path) -> None:
    from backend.main import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        res = await client.get("/api/registry/model-stats/training-trend?days=0")

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
