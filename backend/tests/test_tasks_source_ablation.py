"""`tasks.run_source_ablation_task` の四半期ゲート判定の検証（🆕 P29）."""

from __future__ import annotations

from datetime import datetime as real_datetime

import pytest

from backend import tasks


class _FrozenDatetime(real_datetime):
    _frozen: real_datetime

    @classmethod
    def now(cls, tz: object = None) -> real_datetime:  # type: ignore[override]  # noqa: ARG003
        return cls._frozen


def _freeze(monkeypatch: pytest.MonkeyPatch, iso: str) -> None:
    frozen = real_datetime.fromisoformat(iso)
    fake = type("_Frozen", (_FrozenDatetime,), {"_frozen": frozen})
    monkeypatch.setattr(tasks, "datetime", fake)


@pytest.mark.parametrize("month", [2, 3, 5, 6, 8, 9, 11, 12])
def test_skips_outside_quarter_start_months(monkeypatch: pytest.MonkeyPatch, month: int) -> None:
    _freeze(monkeypatch, f"2026-{month:02d}-01T04:00:00+09:00")
    assert tasks.run_source_ablation_task() == {"status": "skipped_not_quarter_start"}


@pytest.mark.parametrize("month", [1, 4, 7, 10])
def test_runs_on_quarter_start_months_but_skips_on_empty_panel(monkeypatch: pytest.MonkeyPatch, month: int) -> None:
    """四半期開始月では month ゲートを通過し、実際の学習パネル構築（空パネル）まで進むこと."""

    async def _empty_panel(_dates: list[str]) -> object:
        import pandas as pd

        return pd.DataFrame()

    _freeze(monkeypatch, f"2026-{month:02d}-01T04:00:00+09:00")
    monkeypatch.setattr("backend.services.learning.panel_feature_service.build_panel", _empty_panel)

    assert tasks.run_source_ablation_task() == {"status": "skipped_empty_panel"}
