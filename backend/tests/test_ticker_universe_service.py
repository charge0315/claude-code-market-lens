"""ticker_universe_service（🆕 学習対象設定のカスタムリスト選択ダイアログ用）のテスト."""

from __future__ import annotations

from pathlib import Path

import pytest

from backend.models.stocks import TickerInfo
from backend.services.data import ticker_universe_service as svc
from backend.services.db import training_target_db


def _universe() -> list[TickerInfo]:
    return [
        TickerInfo(code="1111", name="あいう銘柄", sector="サービス業"),
        TickerInfo(code="2222", name="かきく銘柄", sector="化学"),
        TickerInfo(code="3333", name="さしす銘柄", sector="化学"),
    ]


async def _universe_awaitable() -> list[TickerInfo]:
    return _universe()


async def test_list_ticker_universe_defaults_to_code_order(migrated_db: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(svc, "_get_ticker_master", lambda: _universe_awaitable())
    monkeypatch.setattr(svc, "_get_latest_volume_map", lambda: _empty_volume_map())

    entries = await svc.list_ticker_universe()

    assert [e.code for e in entries] == ["1111", "2222", "3333"]
    assert all(e.volume is None for e in entries)


async def _empty_volume_map() -> dict[str, float]:
    return {}


async def test_list_ticker_universe_filters_by_sector(migrated_db: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(svc, "_get_ticker_master", lambda: _universe_awaitable())
    monkeypatch.setattr(svc, "_get_latest_volume_map", lambda: _empty_volume_map())

    entries = await svc.list_ticker_universe(sector="化学")

    assert [e.code for e in entries] == ["2222", "3333"]


async def test_list_ticker_universe_filters_by_query(migrated_db: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(svc, "_get_ticker_master", lambda: _universe_awaitable())
    monkeypatch.setattr(svc, "_get_latest_volume_map", lambda: _empty_volume_map())

    entries = await svc.list_ticker_universe(q="2222")

    assert [e.code for e in entries] == ["2222"]


async def test_list_ticker_universe_sorts_by_volume_desc(migrated_db: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(svc, "_get_ticker_master", lambda: _universe_awaitable())

    async def _volumes() -> dict[str, float]:
        return {"1111": 100.0, "2222": 900.0}  # 3333 は volume 情報なし

    monkeypatch.setattr(svc, "_get_latest_volume_map", _volumes)

    entries = await svc.list_ticker_universe(sort="volume_desc")

    assert [e.code for e in entries] == ["2222", "1111", "3333"]


async def test_list_ticker_universe_marks_custom_list_membership(
    migrated_db: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(svc, "_get_ticker_master", lambda: _universe_awaitable())
    monkeypatch.setattr(svc, "_get_latest_volume_map", lambda: _empty_volume_map())
    await training_target_db.add_custom_tickers(["2222"])

    entries = await svc.list_ticker_universe()

    by_code = {e.code: e for e in entries}
    assert by_code["2222"].in_custom_list is True
    assert by_code["1111"].in_custom_list is False


async def test_get_latest_volume_map_returns_empty_when_jquants_not_configured(
    migrated_db: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(type(svc.jquants), "is_configured", property(lambda self: False))
    assert await svc._get_latest_volume_map() == {}


async def test_get_latest_volume_map_returns_volumes_from_ranking_service(
    migrated_db: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(type(svc.jquants), "is_configured", property(lambda self: True))

    async def _fake_resolve_latest_available() -> tuple[str, list[dict[str, object]]]:
        return "2026-09-18", [
            {"Code": "72030", "AdjVo": 1_000_000.0},
            {"Code": "67580", "AdjVo": ""},  # AdjVo 欠損は除外される
        ]

    monkeypatch.setattr(svc.ranking_service, "resolve_latest_available", _fake_resolve_latest_available)

    volumes = await svc._get_latest_volume_map()

    assert volumes == {"7203": 1_000_000.0}
