"""`run_picks_task` の同日重複生成防止ガード.

celery-beat は長時間停止後に再起動すると、due と判定した全エントリを即時発火する
（`_BEAT_SCHEDULE` の日次エントリが軒並み overdue になるため、2026-09-20 に実際発生した
インシデント）。`pipeline.run_picks` 自体は同日冪等ガードを持たない（`POST /api/picks/run`
経由の手動再生成は意図的に毎回新規生成させたいため）ので、beat 起点のタスク層でのみガードする。
"""

from __future__ import annotations

import pytest

from backend import tasks
from backend.services.ledger import prediction_ledger as pl
from backend.services.picks import pipeline as pp


class _FakePickSummary:
    def __init__(self) -> None:
        self.status = "ok"
        self.picks = ["p1"]
        self.rejected: list[object] = []


def test_run_picks_task_skips_when_already_issued_today(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _fake_list_picks(**_kwargs: object) -> list[object]:
        return [object()]

    run_calls: list[str] = []

    async def _fake_run_picks(horizon_type: str) -> _FakePickSummary:
        run_calls.append(horizon_type)
        return _FakePickSummary()

    monkeypatch.setattr(pl, "list_picks", _fake_list_picks)
    monkeypatch.setattr(pp, "run_picks", _fake_run_picks)

    result = tasks.run_picks_task("mid_term")

    assert run_calls == []
    assert result == {"status": "skipped_already_issued_today", "picks": 0, "rejected": 0}


def test_run_picks_task_runs_when_nothing_issued_today(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _fake_list_picks(**_kwargs: object) -> list[object]:
        return []

    run_calls: list[str] = []

    async def _fake_run_picks(horizon_type: str) -> _FakePickSummary:
        run_calls.append(horizon_type)
        return _FakePickSummary()

    monkeypatch.setattr(pl, "list_picks", _fake_list_picks)
    monkeypatch.setattr(pp, "run_picks", _fake_run_picks)

    result = tasks.run_picks_task("short_term")

    assert run_calls == ["short_term"]
    assert result == {"status": "ok", "picks": 1, "rejected": 0}
