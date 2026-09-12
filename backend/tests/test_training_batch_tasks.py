"""P9 銘柄別モデル学習タスク（`tasks.run_*_training_batch_task`）のスモークテスト.

各タスクは `per_ticker_training_service.run_daily_training_batch(model_type)` へ
そのまま委譲するだけの薄いラッパーであることを確認する（実際の学習ロジックは
`test_per_ticker_training_service.py` で検証済み）。
"""

from __future__ import annotations

from collections.abc import Callable

import pytest

from backend import tasks
from backend.services.learning import per_ticker_training_service


class _FakeSummary:
    def __init__(self, model_type: str) -> None:
        self._model_type = model_type

    def to_dict(self) -> dict[str, object]:
        return {"model_type": self._model_type, "trained_this_call": 0}


@pytest.mark.parametrize(
    ("task_fn", "expected_model_type"),
    [
        (tasks.run_xgboost_training_batch_task, "xgboost"),
        (tasks.run_random_forest_training_batch_task, "random_forest"),
        (tasks.run_lstm_training_batch_task, "lstm"),
        (tasks.run_transformer_training_batch_task, "transformer"),
    ],
)
def test_training_batch_task_delegates_to_service_with_correct_model_type(
    monkeypatch: pytest.MonkeyPatch,
    task_fn: Callable[[], dict[str, object]],
    expected_model_type: str,
) -> None:
    seen_model_types: list[str] = []

    async def _fake_run(model_type: str) -> _FakeSummary:
        seen_model_types.append(model_type)
        return _FakeSummary(model_type)

    monkeypatch.setattr(per_ticker_training_service, "run_daily_training_batch", _fake_run)

    result = task_fn()

    assert seen_model_types == [expected_model_type]
    assert result == {"model_type": expected_model_type, "trained_this_call": 0}
