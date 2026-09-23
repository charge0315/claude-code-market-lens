"""`services/portfolio/eod_review_service.run_eod_review` の検証."""

from __future__ import annotations

from pathlib import Path

import pytest

from backend.services.anthropic_errors import AnthropicRateLimitError
from backend.services.db.portfolio_signal_db import insert_signal
from backend.services.portfolio import eod_review_service as svc


class _FakeLLM:
    provider_id = "anthropic"
    model_id = "test-model"

    def __init__(self, response: dict[str, object] | Exception) -> None:
        self._response = response

    async def propose_eod_review(self, *, prompt: str) -> dict[str, object]:  # noqa: ARG002
        if isinstance(self._response, Exception):
            raise self._response
        return dict(self._response)


async def test_run_eod_review_with_no_signals_is_no_activity(migrated_db: Path) -> None:
    review = await svc.run_eod_review("2026-06-02")

    assert review.summary == "本日は判定がありませんでした。"
    assert review.learned_heuristics == []


async def test_run_eod_review_reuses_existing_without_force(migrated_db: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    await insert_signal(
        symbol="7203",
        action="trim",
        stop=900.0,
        target=1100.0,
        confidence=60.0,
        rationale="x",
        evaluated_at="2026-06-02T10:00:00+09:00",
    )

    class _ConfiguredFakeLLM(_FakeLLM):
        is_configured = True

    monkeypatch.setattr(
        svc, "resolve_feature_provider", lambda _feature: _ConfiguredFakeLLM({"summary": "1回目", "heuristics": []})
    )
    first = await svc.run_eod_review("2026-06-02")

    # 2回目は force=False のため LLM を呼ばず既存行をそのまま返すはず（呼ばれたら例外で気付く）。
    monkeypatch.setattr(
        svc, "resolve_feature_provider", lambda _feature: _ConfiguredFakeLLM(RuntimeError("LLM should not be called"))
    )
    second = await svc.run_eod_review("2026-06-02")

    assert first.summary == second.summary == "1回目"
    assert first.created_at == second.created_at


async def test_run_eod_review_force_regenerates(migrated_db: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    await insert_signal(
        symbol="7203",
        action="add",
        stop=900.0,
        target=1100.0,
        confidence=60.0,
        rationale="x",
        evaluated_at="2026-06-02T10:00:00+09:00",
    )

    class _ConfiguredFakeLLM(_FakeLLM):
        is_configured = True

    monkeypatch.setattr(
        svc, "resolve_feature_provider", lambda _feature: _ConfiguredFakeLLM({"summary": "1回目", "heuristics": []})
    )
    first = await svc.run_eod_review("2026-06-02")

    monkeypatch.setattr(
        svc, "resolve_feature_provider", lambda _feature: _ConfiguredFakeLLM({"summary": "2回目", "heuristics": []})
    )
    second = await svc.run_eod_review("2026-06-02", force=True)

    assert first.summary == "1回目"
    assert second.summary == "2回目"


async def test_run_eod_review_falls_back_when_llm_not_configured(migrated_db: Path) -> None:
    await insert_signal(
        symbol="7203",
        action="stop_loss",
        stop=900.0,
        target=1100.0,
        confidence=60.0,
        rationale="x",
        evaluated_at="2026-06-02T10:00:00+09:00",
    )

    review = await svc.run_eod_review("2026-06-02")

    assert "APIキーが未設定" in review.summary
    assert len(review.learned_heuristics) == 1


async def test_run_eod_review_falls_back_on_llm_error(migrated_db: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    await insert_signal(
        symbol="7203",
        action="trim",
        stop=900.0,
        target=1100.0,
        confidence=60.0,
        rationale="x",
        evaluated_at="2026-06-02T10:00:00+09:00",
    )

    class _ConfiguredFakeLLM(_FakeLLM):
        is_configured = True

    monkeypatch.setattr(
        svc, "resolve_feature_provider", lambda _feature: _ConfiguredFakeLLM(AnthropicRateLimitError("eod_review"))
    )

    review = await svc.run_eod_review("2026-06-02")

    assert "LLM 呼び出しに失敗" in review.summary
    assert review.learned_heuristics == []


async def test_get_latest_returns_none_when_no_reviews(migrated_db: Path) -> None:
    assert await svc.get_latest() is None


async def test_get_latest_returns_newest_review_date(migrated_db: Path) -> None:
    await svc.run_eod_review("2026-06-01")
    await svc.run_eod_review("2026-06-03")
    await svc.run_eod_review("2026-06-02")

    latest = await svc.get_latest()

    assert latest is not None
    assert latest.review_date == "2026-06-03"
