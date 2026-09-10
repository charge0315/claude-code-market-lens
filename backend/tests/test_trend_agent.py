"""Trend Tracking Agent（analyzer / sync_service / context）の検証."""

from __future__ import annotations

from pathlib import Path

import pytest

from backend.models.trend_tracking import Trend
from backend.services.data.trend import analyzer, collector, context, sync_service


class _FakeAnthropic:
    """`is_configured` を素の属性で持つ AnthropicClient スタブ."""

    def __init__(self, *, configured: bool) -> None:
        self.is_configured = configured

    async def propose_trends(self, *, prompt: str) -> dict[str, object]:  # noqa: ARG002
        return {"trends": []}


def _set_anthropic(monkeypatch: pytest.MonkeyPatch, fake: _FakeAnthropic) -> None:
    monkeypatch.setattr(analyzer, "anthropic_client", fake)


# --- analyzer ---


def test_coerce_trends_clamps_and_defaults_invalid_enums() -> None:
    raw = [
        {
            "theme_name": "テーマA",
            "summary": "要約",
            "lifecycle_stage": "BOGUS",
            "impact_horizon": "x",
            "sentiment_score": 5.0,  # → 1.0 にクランプ
            "momentum_score": -10.0,  # → 0.0 にクランプ
            "keywords": ["k1", "k2"],
            "related_tickers": [{"ticker": "7203.T", "correlation_rationale": "根拠"}],
        },
        {"theme_name": "", "summary": "空テーマは除外"},
    ]
    trends = analyzer._coerce_trends(
        raw, valid={"7203": "トヨタ自動車"}, now_iso="2026-09-11T09:00:00+09:00", date_key="20260911"
    )
    assert len(trends) == 1
    t = trends[0]
    assert t.lifecycle_stage == "EMERGING"  # 不正 → 既定
    assert t.impact_horizon == "MID"
    assert t.sentiment_score == 1.0
    assert t.momentum_score == 0.0
    assert t.related_tickers[0].ticker == "7203"
    assert t.related_tickers[0].name == "トヨタ自動車"


def test_coerce_related_drops_codes_not_in_master() -> None:
    out = analyzer._coerce_related(
        [
            {"ticker": "7203", "correlation_rationale": "有効"},
            {"ticker": "9999", "correlation_rationale": "master に無い"},
            {"ticker": "7203", "name": "x"},  # rationale 欠落 → 除外
        ],
        valid={"7203": "トヨタ自動車"},
    )
    assert [r.ticker for r in out] == ["7203"]


async def test_analyze_returns_mock_when_not_configured(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_anthropic(monkeypatch, _FakeAnthropic(configured=False))
    trends = await analyzer.analyze(["見出し"], ["セクターノート"])
    assert trends and all(isinstance(t, Trend) for t in trends)
    assert trends[0].theme_name == "次世代半導体パッケージング"


async def test_analyze_uses_llm_when_configured(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _FakeAnthropic(configured=True)

    async def fake_propose(*, prompt: str) -> dict[str, object]:  # noqa: ARG001
        return {
            "trends": [
                {
                    "theme_name": "LLM テーマ",
                    "summary": "LLM 要約",
                    "lifecycle_stage": "EXPANDING",
                    "impact_horizon": "LONG",
                    "sentiment_score": 0.5,
                    "momentum_score": 70,
                }
            ]
        }

    async def fake_valid() -> dict[str, str]:
        return {}

    fake.propose_trends = fake_propose  # type: ignore[method-assign]
    _set_anthropic(monkeypatch, fake)
    monkeypatch.setattr(analyzer, "_valid_codes_async", fake_valid)
    trends = await analyzer.analyze(["h"], ["s"])
    assert [t.theme_name for t in trends] == ["LLM テーマ"]


# --- sync_service ---


async def test_sync_persists_and_ttl_reuses(migrated_db: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _set_anthropic(monkeypatch, _FakeAnthropic(configured=False))

    async def fake_collect() -> collector.CollectedSignals:
        return collector.CollectedSignals(headlines=[], sector_notes=[], source_summary="", is_mock=True)

    monkeypatch.setattr(sync_service.collector, "collect_signals", fake_collect)

    snap1 = await sync_service.sync_trends()
    assert snap1.status in ("mock", "not_configured")
    assert snap1.trends

    latest = await sync_service.get_latest()
    assert latest is not None and latest.snapshot_at == snap1.snapshot_at

    # TTL 内 → 同じスナップショット（再収集しない）。
    called = {"n": 0}

    async def counting_collect() -> collector.CollectedSignals:
        called["n"] += 1
        return collector.CollectedSignals(is_mock=True)

    monkeypatch.setattr(sync_service.collector, "collect_signals", counting_collect)
    snap2 = await sync_service.sync_trends()
    assert snap2.snapshot_at == snap1.snapshot_at
    assert called["n"] == 0


async def test_get_latest_none_when_empty(migrated_db: Path) -> None:
    assert await sync_service.get_latest() is None


# --- context ---


def test_render_trends_orders_by_momentum_and_returns_none_when_empty() -> None:
    assert context.render_trends([]) is None
    now = "2026-09-11T09:00:00+09:00"
    trends = [
        Trend(
            trend_id="t1",
            timestamp=now,
            theme_name="低モメンタム",
            summary="s",
            lifecycle_stage="EMERGING",
            sentiment_score=0.1,
            momentum_score=20,
            impact_horizon="MID",
        ),
        Trend(
            trend_id="t2",
            timestamp=now,
            theme_name="高モメンタム",
            summary="s",
            lifecycle_stage="PEAK",
            sentiment_score=0.5,
            momentum_score=90,
            impact_horizon="SHORT",
        ),
    ]
    block = context.render_trends(trends)
    assert block is not None
    assert block.index("高モメンタム") < block.index("低モメンタム")


async def test_render_trend_context_none_without_snapshot(migrated_db: Path) -> None:
    assert await context.render_trend_context() is None
