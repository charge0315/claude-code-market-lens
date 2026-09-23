"""過去日リプレイのループ本体（🆕 P37）の結合テスト（合成データ・DB 実テーブル）."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from backend.services.db import model_registry_db, replay_db
from backend.services.replay import engine
from backend.services.replay import price_store as ps
from backend.services.replay.ml import ReplayMlConfig

_N_DAYS = 330
_N_CODES = 30


def _dates() -> list[str]:
    return [d.strftime("%Y-%m-%d") for d in pd.bdate_range("2021-01-04", periods=_N_DAYS)]


def _store() -> ps.PriceStore:
    rng = np.random.default_rng(7)
    rows: list[dict[str, object]] = []
    for i in range(_N_CODES + 1):
        code = "13060" if i == _N_CODES else f"{1000 + i}0"
        drift = 0.0002 if i == _N_CODES else (i - _N_CODES / 2) * 0.0004
        close = 1000.0 * np.exp(np.cumsum(rng.normal(drift, 0.02, _N_DAYS)))
        vol = rng.integers(10_000, 1_000_000, _N_DAYS)
        for d, c, v in zip(_dates(), close, vol, strict=True):
            rows.append(
                {"Date": d, "Code": code, "AdjO": c, "AdjH": c * 1.02, "AdjL": c * 0.98, "AdjC": c, "AdjVo": float(v)}
            )
    return ps.PriceStore(pd.DataFrame(rows))


_CFG = engine.ReplayConfig(
    retrain_every_bdays=10, ml=ReplayMlConfig(horizon=10, window_bdays=150, stride_bdays=3, resolve_buffer_bdays=3)
)


async def _create(run_id: str, start_idx: int, end_idx: int) -> None:
    dates = _dates()
    await replay_db.create_run(run_id, start_date=dates[start_idx], end_date=dates[end_idx], config=_CFG.to_dict())


async def test_run_replay_completes_with_picks_outcomes_and_challenger(migrated_db: Path) -> None:
    await _create("run-e2e-0001", 260, 329)

    status = await engine.run_replay("run-e2e-0001", _store())

    assert status == "completed"
    run = await replay_db.get_run("run-e2e-0001")
    assert run is not None
    assert run["cursor_date"] == _dates()[329]
    counts = await replay_db.count_picks("run-e2e-0001")
    assert counts.get("short_term", 0) > 0 and counts.get("mid_term", 0) > 0
    assert len(await replay_db.list_resolved("run-e2e-0001", horizon_days=1)) > 0
    assert len(await replay_db.list_retrains("run-e2e-0001")) >= 2

    summary = run["summary"]
    assert isinstance(summary, dict)
    assert summary["horizons"]["short_term"]["1"]["performance"]["n"] > 0
    challenger = summary["challenger_version"]
    assert isinstance(challenger, str) and challenger.startswith("replay-run-e2e-")
    # 登録はするが champion にはしない（本番入りは人手承認の昇格ゲートのみ）
    assert await model_registry_db.get_model(challenger) is not None
    assert await model_registry_db.get_champion("ml_pool") is None


async def test_every_pick_bracket_is_consistent(migrated_db: Path) -> None:
    await _create("run-e2e-0002", 300, 310)
    await engine.run_replay("run-e2e-0002", _store())

    for horizon in ("short_term", "mid_term"):
        for p in await replay_db.list_pending_picks("run-e2e-0002"):
            if p["horizon_type"] != horizon:
                continue
            assert float(str(p["stop"])) < float(str(p["entry"])) < float(str(p["target"]))


async def test_resume_continues_from_cursor_without_duplicates(migrated_db: Path) -> None:
    store = _store()
    await _create("run-e2e-0003", 290, 309)
    await replay_db.update_run("run-e2e-0003", cursor_date=_dates()[299])  # 前半は処理済みとみなす

    await engine.run_replay("run-e2e-0003", store)
    first = await replay_db.count_picks("run-e2e-0003")
    # 前半（〜cursor）の日付にはピックが作られていない
    pending = await replay_db.list_pending_picks("run-e2e-0003")
    assert min(str(p["issued_at"]) for p in pending) > _dates()[299]

    # 完了済みカーソルでもう一度回しても何も増えない
    await replay_db.update_run("run-e2e-0003", status="pending")
    await engine.run_replay("run-e2e-0003", store)
    assert await replay_db.count_picks("run-e2e-0003") == first


async def test_stop_request_halts_after_current_day(migrated_db: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    await _create("run-e2e-0004", 300, 320)
    calls = {"n": 0}

    async def stop_after_two(_run_id: str) -> bool:
        calls["n"] += 1
        return calls["n"] >= 2

    monkeypatch.setattr(engine, "_should_stop", stop_after_two)

    status = await engine.run_replay("run-e2e-0004", _store())

    assert status == "stopped"
    run = await replay_db.get_run("run-e2e-0004")
    assert run is not None and run["status"] == "stopped"
    assert run["cursor_date"] == _dates()[301]


def test_config_round_trip() -> None:
    assert engine.ReplayConfig.from_dict(_CFG.to_dict()) == _CFG
    assert engine.ReplayConfig.from_dict({}) == engine.ReplayConfig()


async def test_stop_requested_before_start_is_honored(migrated_db: Path) -> None:
    await _create("run-e2e-0005", 300, 305)
    await replay_db.update_run("run-e2e-0005", status="stopping")

    assert await engine.run_replay("run-e2e-0005", _store()) == "stopped"
    run = await replay_db.get_run("run-e2e-0005")
    assert run is not None and run["status"] == "stopped" and run["cursor_date"] is None
