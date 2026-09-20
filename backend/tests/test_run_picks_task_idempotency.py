"""`run_picks_task` の平日ガード・同日重複生成防止ガード.

celery-beat は長時間停止後に再起動すると、due と判定した全エントリを即時発火する
（`_BEAT_SCHEDULE` の日次エントリが軒並み overdue になるため、2026-09-20 に実際発生した
インシデント）。`pipeline.run_picks` 自体は同日冪等ガードを持たない（`POST /api/picks/run`
経由の手動再生成は意図的に毎回新規生成させたいため）ので、beat 起点のタスク層でのみガードする。

さらに 2026-09-20（日曜）の追いつき起動では、休場日にもかかわらず金曜終値ベースの無効な
ピックが実際に生成される事故が発生した。`run_picks_task` には平日判定（`_is_weekday_jst`、
`run_portfolio_monitor_task` 等が既に使っているものと同一）が無かったため、これも追加する。
"""

from __future__ import annotations

from datetime import datetime as real_datetime

import pytest

from backend import tasks
from backend.services.ledger import prediction_ledger as pl
from backend.services.picks import pipeline as pp


class _FakePickSummary:
    def __init__(self) -> None:
        self.status = "ok"
        self.picks = ["p1"]
        self.rejected: list[object] = []


class _FrozenDatetime(real_datetime):
    _frozen: real_datetime

    @classmethod
    def now(cls, tz: object = None) -> real_datetime:  # type: ignore[override]  # noqa: ARG003
        return cls._frozen


def _freeze(monkeypatch: pytest.MonkeyPatch, iso: str) -> None:
    frozen = real_datetime.fromisoformat(iso)
    fake = type("_Frozen", (_FrozenDatetime,), {"_frozen": frozen})
    monkeypatch.setattr(tasks, "datetime", fake)


def _wire(monkeypatch: pytest.MonkeyPatch, *, existing_today: bool) -> list[str]:
    async def _fake_list_picks(**_kwargs: object) -> list[object]:
        return [object()] if existing_today else []

    run_calls: list[str] = []

    async def _fake_run_picks(horizon_type: str) -> _FakePickSummary:
        run_calls.append(horizon_type)
        return _FakePickSummary()

    monkeypatch.setattr(pl, "list_picks", _fake_list_picks)
    monkeypatch.setattr(pp, "run_picks", _fake_run_picks)
    return run_calls


def test_run_picks_task_skips_on_weekend_without_touching_ledger(monkeypatch: pytest.MonkeyPatch) -> None:
    _freeze(monkeypatch, "2026-09-20T07:30:00+09:00")  # 日曜（2026-09-20 に実際発生した休場日誤発火）
    run_calls = _wire(monkeypatch, existing_today=False)

    result = tasks.run_picks_task("short_term")

    assert run_calls == []
    assert result == {"status": "skipped_non_trading_day", "picks": 0, "rejected": 0}


def test_run_picks_task_skips_on_national_holiday_weekday(monkeypatch: pytest.MonkeyPatch) -> None:
    """曜日は平日でも祝日（2026-09-21 敬老の日）なら skip する."""
    _freeze(monkeypatch, "2026-09-21T07:30:00+09:00")  # 月曜・敬老の日
    run_calls = _wire(monkeypatch, existing_today=False)

    result = tasks.run_picks_task("mid_term")

    assert run_calls == []
    assert result == {"status": "skipped_non_trading_day", "picks": 0, "rejected": 0}


def test_run_picks_task_skips_when_already_issued_today(monkeypatch: pytest.MonkeyPatch) -> None:
    _freeze(monkeypatch, "2026-06-02T07:30:00+09:00")  # 火曜
    run_calls = _wire(monkeypatch, existing_today=True)

    result = tasks.run_picks_task("mid_term")

    assert run_calls == []
    assert result == {"status": "skipped_already_issued_today", "picks": 0, "rejected": 0}


def test_run_picks_task_runs_on_weekday_when_nothing_issued_today(monkeypatch: pytest.MonkeyPatch) -> None:
    _freeze(monkeypatch, "2026-06-02T07:30:00+09:00")  # 火曜
    run_calls = _wire(monkeypatch, existing_today=False)

    result = tasks.run_picks_task("short_term")

    assert run_calls == ["short_term"]
    assert result == {"status": "ok", "picks": 1, "rejected": 0}
