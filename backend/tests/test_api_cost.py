"""API コスト計測の検証（Market Lens から移植 + Alpha Forge DB へ適応）."""

from __future__ import annotations

from pathlib import Path

import pytest

from backend.services import api_cost


class _Usage:
    def __init__(self, **kw: object) -> None:
        for k, v in kw.items():
            setattr(self, k, v)


def test_estimate_cost_sonnet_and_opus() -> None:
    cost, known = api_cost.estimate_cost("claude-sonnet-5", input_tokens=1_000_000, output_tokens=0)
    assert known is True
    assert cost == pytest.approx(3.0)
    cost_opus, _ = api_cost.estimate_cost("claude-opus-5", input_tokens=0, output_tokens=1_000_000)
    assert cost_opus == pytest.approx(75.0)


def test_estimate_cost_unknown_model_uses_fallback_pricing() -> None:
    cost, known = api_cost.estimate_cost("claude-fable-5", input_tokens=1_000_000, output_tokens=0)
    assert known is False
    assert cost == pytest.approx(3.0)  # Sonnet 相当のフォールバック


def test_estimate_cost_includes_cache_multipliers() -> None:
    cost, _ = api_cost.estimate_cost(
        "claude-sonnet-5", input_tokens=0, output_tokens=0, cache_read_tokens=1_000_000, cache_write_tokens=1_000_000
    )
    # read: 3.0*0.1 + write: 3.0*1.25 = 0.3 + 3.75
    assert cost == pytest.approx(4.05)


def test_int_attr_rejects_bool_and_coerces_float() -> None:
    assert api_cost._int_attr(_Usage(x=True), "x") == 0
    assert api_cost._int_attr(_Usage(x=12.9), "x") == 12
    assert api_cost._int_attr(_Usage(), "missing") == 0


async def test_record_usage_upserts_and_summary_aggregates(migrated_db: Path) -> None:
    usage = _Usage(input_tokens=1_000_000, output_tokens=500_000)
    await api_cost.record_usage(feature="stock_pick", model="claude-sonnet-5", usage=usage)
    await api_cost.record_usage(feature="stock_pick", model="claude-sonnet-5", usage=usage)

    summary = await api_cost.build_api_cost_summary(days=7)
    assert summary.total_calls == 2
    assert summary.by_feature["stock_pick"] == pytest.approx(2 * (3.0 + 0.5 * 15.0), rel=1e-6)
    assert summary.rows[0].feature == "stock_pick"
    assert summary.rows[0].call_count == 2


async def test_record_usage_is_best_effort_on_none(migrated_db: Path) -> None:
    await api_cost.record_usage(feature="chat", model="claude-sonnet-5", usage=None)
    summary = await api_cost.build_api_cost_summary(days=1)
    assert summary.total_calls == 0


async def test_is_daily_limit_exceeded_false_when_under_limit(
    migrated_db: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(api_cost, "settings", api_cost.settings.model_copy(update={"llm_daily_cost_limit_usd": 5.0}))
    await api_cost.record_usage(
        feature="stock_pick", model="claude-sonnet-5", usage=_Usage(input_tokens=1000, output_tokens=0)
    )

    assert await api_cost.is_daily_limit_exceeded() is False


async def test_is_daily_limit_exceeded_true_when_at_or_over_limit(
    migrated_db: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # sonnet: 1M input tokens = $3.0。上限を $2.0 に下げれば超過扱いになる。
    monkeypatch.setattr(api_cost, "settings", api_cost.settings.model_copy(update={"llm_daily_cost_limit_usd": 2.0}))
    await api_cost.record_usage(
        feature="stock_pick", model="claude-sonnet-5", usage=_Usage(input_tokens=1_000_000, output_tokens=0)
    )

    assert await api_cost.is_daily_limit_exceeded() is True
