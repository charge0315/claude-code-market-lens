"""決着記録バッチの検証（純関数の sim + オーケストレーション）."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from backend.models.pick import LedgerEntry, SubScores
from backend.services.ledger import outcome_resolver as orv
from backend.services.ledger import prediction_ledger as pl


def _bars(rows: list[tuple[str, float, float, float, float]]) -> pd.DataFrame:
    idx = pd.to_datetime([r[0] for r in rows])
    return pd.DataFrame(
        {
            "Open": [r[1] for r in rows],
            "High": [r[2] for r in rows],
            "Low": [r[3] for r in rows],
            "Close": [r[4] for r in rows],
        },
        index=idx,
    )


def test_simulate_fill_within_window() -> None:
    bars = _bars(
        [
            ("2026-09-11", 1000, 1010, 1005, 1008),  # issued day（含めない）
            ("2026-09-14", 1006, 1012, 999, 1010),  # 安値 999 <= entry 1000 → 約定
        ]
    )
    fill_day, fill_price = orv.simulate_fill(bars, "2026-09-11T08:50:00+09:00", entry=1000)
    assert fill_day == "2026-09-14"
    assert fill_price == 1000.0  # min(entry, open 1006)


def test_simulate_fill_no_fill_returns_none() -> None:
    bars = _bars([("2026-09-11", 1000, 1010, 1005, 1008), ("2026-09-14", 1006, 1012, 1004, 1010)])
    assert orv.simulate_fill(bars, "2026-09-11", entry=1000)[0] is None


def test_resolve_horizon_take_profit_first() -> None:
    bars = _bars(
        [
            ("2026-09-14", 1000, 1010, 1000, 1005),  # fill day（含めない）
            ("2026-09-15", 1006, 1020, 1004, 1018),  # ← ここで target 1015 到達
            ("2026-09-16", 1018, 1030, 1012, 1025),
        ]
    )
    r = orv.resolve_horizon(bars, "2026-09-14", fill_price=1000.0, stop=980.0, target=1015.0, horizon_days=5)
    assert r is not None
    realized, hit_stop, hit_target, first_hit, mfe, mae = r
    assert hit_target is True and hit_stop is False and first_hit == "target"
    assert realized == pytest.approx(0.015)  # max(target 1015, open 1006) / 1000 - 1
    assert mfe >= 0.015 and mae <= mfe


def test_resolve_horizon_stop_loss_priority_on_same_day() -> None:
    bars = _bars(
        [
            ("2026-09-14", 1000, 1010, 1000, 1005),
            ("2026-09-15", 1002, 1030, 970, 1000),  # 高値 target 到達 & 安値 stop 到達 → 損切り優先
        ]
    )
    r = orv.resolve_horizon(bars, "2026-09-14", fill_price=1000.0, stop=980.0, target=1015.0, horizon_days=5)
    assert r is not None
    _realized, hit_stop, hit_target, first_hit, _mfe, _mae = r
    assert hit_stop is True and first_hit == "stop"


def test_resolve_horizon_time_exit() -> None:
    bars = _bars(
        [
            ("2026-09-14", 1000, 1010, 1000, 1005),
            ("2026-09-15", 1006, 1012, 1002, 1010),
            ("2026-09-16", 1010, 1014, 1006, 1012),
        ]
    )
    r = orv.resolve_horizon(bars, "2026-09-14", fill_price=1000.0, stop=900.0, target=1100.0, horizon_days=2)
    assert r is not None
    realized, hit_stop, hit_target, first_hit, _mfe, _mae = r
    assert first_hit == "none" and not hit_stop and not hit_target
    assert realized == pytest.approx(0.012)  # last close 1012 / 1000 - 1


def test_horizon_is_mature() -> None:
    assert orv.horizon_is_mature("2026-01-01", 20, today="2026-03-01") is True
    assert orv.horizon_is_mature("2026-09-10", 60, today="2026-09-20") is False


def test_build_outcomes_multi_horizon_and_excess() -> None:
    # mid_term → ホライズン 5/20/60。今日を十分未来にして 5 だけ成熟させる。
    bars = _bars(
        [("2026-09-11", 1000, 1010, 1005, 1008)]
        + [("2026-09-14", 1006, 1012, 999, 1010)]  # 約定
        + [(f"2026-09-{15 + i}", 1010.0 + i, 1020.0 + i, 1005.0 + i, 1012.0 + i) for i in range(8)]
    )
    bench = _bars(
        [("2026-09-14", 100.0, 100.0, 100.0, 100.0)]
        + [(f"2026-09-{15 + i}", 101.0, 101.0, 101.0, 101.0 + i) for i in range(8)]
    )
    outcomes, status = orv.build_outcomes(
        horizon_type="mid_term",
        issued_at="2026-09-11T08:50:00+09:00",
        entry=1000.0,
        stop=950.0,
        target=1100.0,
        bars=bars,
        bench_bars=bench,
        today="2026-10-15",  # 5 営業日ホライズンのみ成熟
    )
    assert status == "filled"
    assert [o.horizon_days for o in outcomes] == [5]
    o5 = outcomes[0]
    assert o5.excess_return == pytest.approx(o5.realized_return - o5.benchmark_return)


async def test_resolve_pending_writes_outcomes(migrated_db: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    entry = LedgerEntry(
        pick_id="p1",
        run_id="r1",
        issued_at="2026-01-06T08:50:00+09:00",
        horizon_type="short_term",
        symbol="7203",
        direction="bullish",
        entry=1000.0,
        stop=960.0,
        target=1040.0,
        sub_scores=SubScores(technical=60, trend=55, fundamental=52, sentiment=50),
        composite_score=60.0,
        concordance=0.6,
        confidence_raw=70.0,
        confidence=72.0,
        confidence_bucket="high",
        feature_snapshot={},
        rationale_struct={},
        rationale_text="x",
        model_version="baseline-2026-09-11",
        source_contributions={},
        created_at="2026-01-06T08:50:01+09:00",
    )
    await pl.insert_pick(entry)

    bars = _bars(
        [
            ("2026-01-06", 1000, 1005, 998, 1002),
            ("2026-01-07", 1001, 1010, 995, 1008),  # 約定（安値 995 <= 1000）
            ("2026-01-08", 1008, 1045, 1006, 1042),  # target 1040 到達
            ("2026-01-09", 1042, 1050, 1038, 1046),
            ("2026-01-13", 1046, 1052, 1040, 1048),
        ]
    )
    monkeypatch.setattr(orv, "get_stock_data", lambda _s, period="1y": bars)
    monkeypatch.setattr(orv, "_safe_fetch_macro", lambda _s: _bars([("2026-01-07", 100, 100, 100, 100)]))

    summary = await orv.resolve_pending(max_picks=10)
    assert summary.resolved_picks == 1
    assert summary.written_outcomes >= 1

    from backend.services.db import pick_outcome_db

    rows = await pick_outcome_db.list_outcomes("p1")
    assert {r["horizon_days"] for r in rows} == {1, 2, 3}
    assert all(r["first_hit"] == "target" for r in rows)
