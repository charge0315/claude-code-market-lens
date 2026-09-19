"""training_target_service（🆕 学習対象設定）のテスト."""

from __future__ import annotations

from pathlib import Path

import pytest

from backend.models.stocks import TickerInfo
from backend.services.db import portfolio_db, training_target_db
from backend.services.learning import training_target_service as svc


def _universe() -> list[TickerInfo]:
    return [
        TickerInfo(code="1111", name="銘柄A", sector="サービス業"),
        TickerInfo(code="2222", name="銘柄B", sector="化学"),
        TickerInfo(code="3333", name="銘柄C", sector="化学"),
    ]


async def test_get_settings_falls_back_to_defaults_when_unsaved(migrated_db: Path) -> None:
    settings = await svc.get_settings()
    assert settings.target_mode == "all"
    assert settings.max_parallel_workers == 4


async def test_update_settings_persists_and_round_trips(migrated_db: Path) -> None:
    updated = await svc.update_settings(target_mode="custom", max_parallel_workers=8)
    assert updated.target_mode == "custom"
    assert updated.max_parallel_workers == 8

    fetched = await svc.get_settings()
    assert fetched.target_mode == "custom"
    assert fetched.max_parallel_workers == 8


async def test_update_settings_clamps_max_parallel_workers(migrated_db: Path) -> None:
    too_high = await svc.update_settings(max_parallel_workers=999)
    assert too_high.max_parallel_workers == 16

    too_low = await svc.update_settings(max_parallel_workers=0)
    assert too_low.max_parallel_workers == 1


async def test_update_settings_partial_update_keeps_other_field(migrated_db: Path) -> None:
    await svc.update_settings(target_mode="portfolio", max_parallel_workers=6)
    only_mode = await svc.update_settings(target_mode="all")
    assert only_mode.target_mode == "all"
    assert only_mode.max_parallel_workers == 6


async def test_resolve_training_universe_all_mode_returns_full_master(
    migrated_db: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(svc, "_get_ticker_master", lambda: _universe_awaitable())

    universe = await svc.resolve_training_universe()
    assert [t.code for t in universe] == ["1111", "2222", "3333"]


async def _universe_awaitable() -> list[TickerInfo]:
    return _universe()


async def test_resolve_training_universe_portfolio_mode_filters_to_holdings(
    migrated_db: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(svc, "_get_ticker_master", lambda: _universe_awaitable())
    await svc.update_settings(target_mode="portfolio")
    await portfolio_db.insert_holding(symbol="2222", quantity=100, avg_cost=1000.0, acquired_at="2026-09-01")

    universe = await svc.resolve_training_universe()
    assert [t.code for t in universe] == ["2222"]


async def test_resolve_training_universe_portfolio_mode_empty_does_not_fallback_to_all(
    migrated_db: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(svc, "_get_ticker_master", lambda: _universe_awaitable())
    await svc.update_settings(target_mode="portfolio")

    universe = await svc.resolve_training_universe()
    assert universe == []


async def test_resolve_training_universe_picked_mode_uses_recent_picks(
    migrated_db: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(svc, "_get_ticker_master", lambda: _universe_awaitable())

    async def _fake_picked(_issued_from: str) -> set[str]:
        return {"3333"}

    monkeypatch.setattr(svc.prediction_ledger, "list_picked_symbols_since", _fake_picked)
    await svc.update_settings(target_mode="picked")

    universe = await svc.resolve_training_universe()
    assert [t.code for t in universe] == ["3333"]


async def test_resolve_training_universe_custom_mode_excludes_unknown_codes(
    migrated_db: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(svc, "_get_ticker_master", lambda: _universe_awaitable())
    await svc.update_settings(target_mode="custom")
    await training_target_db.add_custom_tickers(["1111", "9999"])  # 9999 はマスタに存在しない

    universe = await svc.resolve_training_universe()
    assert [t.code for t in universe] == ["1111"]


async def test_get_priority_override_map_empty_for_non_custom_modes(migrated_db: Path) -> None:
    await svc.update_settings(target_mode="all")
    assert await svc.get_priority_override_map() == {}


async def test_get_priority_override_map_returns_added_at_for_custom_mode(migrated_db: Path) -> None:
    await svc.update_settings(target_mode="custom")
    await training_target_db.add_custom_tickers(["1111"])

    overrides = await svc.get_priority_override_map()
    assert set(overrides.keys()) == {"1111"}


async def test_replace_custom_tickers_preserves_added_at_for_kept_tickers(migrated_db: Path) -> None:
    await training_target_db.add_custom_tickers(["1111"])
    before = await training_target_db.get_custom_ticker_added_at_map()

    await training_target_db.replace_custom_tickers(["1111", "2222"])
    after = await training_target_db.get_custom_ticker_added_at_map()

    assert after["1111"] == before["1111"]
    assert "2222" in after


async def test_replace_custom_tickers_removes_deselected(migrated_db: Path) -> None:
    await training_target_db.add_custom_tickers(["1111", "2222"])
    await training_target_db.replace_custom_tickers(["1111"])

    assert await training_target_db.list_custom_tickers() == ["1111"]
