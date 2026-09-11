"""評価指標の集計・永続化と、ledger / eval API の検証（CL-3）."""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from backend.models.pick import LedgerEntry, SubScores
from backend.services.db import eval_db, pick_outcome_db
from backend.services.ledger import eval_service
from backend.services.ledger import prediction_ledger as pl


def _pick(i: int, *, confidence: float, composite: float) -> LedgerEntry:
    return LedgerEntry(
        pick_id=f"p{i}",
        run_id="r1",
        issued_at=f"2026-06-{i:02d}T08:50:00+09:00",
        horizon_type="mid_term",
        symbol=f"{7000 + i}",
        direction="bullish",
        entry=1000.0,
        stop=950.0,
        target=1100.0,
        sub_scores=SubScores(technical=60, trend=55, fundamental=52, sentiment=50),
        composite_score=composite,
        concordance=0.6,
        confidence_raw=confidence,
        confidence=confidence,
        confidence_bucket=pl.confidence_bucket(confidence),
        feature_snapshot={},
        rationale_struct={},
        rationale_text="x",
        model_version="baseline-2026-09-11",
        source_contributions={},
        created_at="2026-06-01T08:50:01+09:00",
    )


async def _seed(n: int = 12) -> None:
    """高確度ほど勝ちやすい・composite が高いほど excess が高い、を満たす決着データを作る."""
    for i in range(1, n + 1):
        conf = 40.0 + (i / n) * 55.0  # 40〜95
        comp = 45.0 + (i / n) * 30.0
        await pl.insert_pick(_pick(i, confidence=conf, composite=comp))
        win = i > n // 3  # 下位 1/3 は負け
        realized = 0.05 * (i / n) - 0.02
        await pick_outcome_db.upsert_outcome(
            pick_id=f"p{i}",
            horizon_days=20,
            resolved_at="2026-08-01T16:38:00+09:00",
            realized_return=realized,
            win=win,
            hit_stop=not win,
            hit_target=win,
            first_hit="target" if win else "stop",
            mfe=abs(realized) + 0.01,
            mae=-abs(realized) - 0.01,
            benchmark_return=0.01,
            excess_return=realized - 0.01,
            confidence_bucket=pl.confidence_bucket(conf),
            direction="bullish",
        )


async def test_compute_and_persist_writes_snapshots_and_calibration(migrated_db: Path) -> None:
    await _seed()
    metrics = await eval_service.compute_and_persist(scope="mid_term", horizon_days=20)
    assert metrics["sample_n"] == 12.0
    assert metrics["win_rate"] is not None
    assert metrics["ic"] is not None  # composite と excess は連動させたので非 None

    snaps = await eval_db.list_eval_snapshots(scope="mid_term", metric_name="win_rate")
    assert snaps and snaps[-1]["metric_value"] == metrics["win_rate"]

    curve = await eval_db.get_latest_calibration_curve(scope="mid_term", horizon_days=20)
    assert curve is not None
    # 12 件（>= _MIN_PLATT_SAMPLES=10、< _MIN_ISOTONIC_SAMPLES=40）→ Platt で較正される。
    assert curve["is_calibrated"] == 1
    assert isinstance(curve["points"], list) and curve["points"]

    from backend.services.registry import calibration

    loaded = calibration.load_calibrator("mid_term", 20)
    assert loaded is not None and loaded[1] == "platt"


async def test_compute_and_persist_skips_when_too_few(migrated_db: Path) -> None:
    await pl.insert_pick(_pick(1, confidence=70.0, composite=60.0))
    out = await eval_service.compute_and_persist(scope="mid_term", horizon_days=20)
    assert out == {"sample_n": 0.0}  # 決着行ゼロ → サンプル不足


@pytest_asyncio.fixture
async def client(migrated_db: Path) -> AsyncIterator[AsyncClient]:
    from backend.main import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac


async def test_ledger_and_eval_endpoints(client: AsyncClient) -> None:
    await _seed()
    await eval_service.compute_and_persist(scope="mid_term", horizon_days=20)

    ledger = (await client.get("/api/ledger?horizon=mid_term")).json()
    assert ledger["success"] and len(ledger["data"]) == 12

    outcomes = (await client.get("/api/ledger/p5/outcomes")).json()
    assert outcomes["success"] and outcomes["data"][0]["horizon_days"] == 20

    growth = (await client.get("/api/eval/growth?scope=mid_term&metric=ic")).json()
    assert growth["success"] and growth["data"]

    calib = (await client.get("/api/eval/calibration?scope=mid_term&horizon=20")).json()
    assert calib["success"] and calib["data"]["points"]

    eq = (await client.get("/api/eval/equity-curve?scope=mid_term&horizon=20")).json()
    assert eq["success"] and eq["data"]["n"] == 12 and len(eq["data"]["equity"]) == 12

    fw = (await client.get("/api/eval/factor-weights?horizon_days=20")).json()
    assert fw["success"]
    assert set(fw["data"]["shadow_weights"].keys()) == set(fw["data"]["production_weights"].keys())
    assert sum(fw["data"]["shadow_weights"].values()) == pytest.approx(1.0, abs=1e-3)

    weekly = (await client.get("/api/eval/weekly-learning?window_days=7")).json()
    assert weekly["success"]
    assert weekly["data"]["window_days"] == 7
    assert isinstance(weekly["data"]["metric_deltas"], list)
