"""企業ランキングサービスの検証（Market Lens から移植）.

J-Quants は叩かず、全銘柄一括取得（fetch_all_daily_bars）と銘柄マスタをモックする。
"""

from __future__ import annotations

import datetime
from collections.abc import Iterator

import pytest

from backend.services.data import ranking_service as rs
from backend.services.data.jquants_errors import JQuantsClientError, JQuantsError


@pytest.fixture(autouse=True)
def _reset_caches() -> Iterator[None]:
    rs._rankings_cache = None
    rs._yearly_cache = None
    rs._name_map_cache = None
    rs._latest_date_cache = None
    yield
    rs._rankings_cache = None
    rs._yearly_cache = None
    rs._name_map_cache = None
    rs._latest_date_cache = None


def _bar(code: str, close: float, volume: float = 1000) -> dict[str, object]:
    return {"Code": code, "AdjC": str(close), "AdjVo": str(volume)}


def test_generate_breadth_comment() -> None:
    assert "買い優勢" in rs._generate_breadth_comment(10, 3)
    assert "売り優勢" in rs._generate_breadth_comment(2, 8)
    assert "拮抗" in rs._generate_breadth_comment(5, 5)


def test_index_by_code_skips_invalid_rows() -> None:
    out = rs._index_by_code([_bar("72030", 100), {"Code": "", "AdjC": "1"}, {"Code": "6758", "AdjC": None}])
    assert set(out) == {"72030"}
    assert out["72030"]["close"] == 100.0


def test_parse_subscription_range() -> None:
    exc = JQuantsClientError("/x", 400, body="Your subscription covers the following dates: 2024-04-25 ~ 2026-04-25.")
    assert rs.parse_subscription_range(exc) == ("2024-04-25", "2026-04-25")
    assert rs.parse_subscription_range(JQuantsClientError("/x", 400, body="nope")) is None


async def test_walk_back_for_bars_skips_non_trading_days(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []

    async def fake_bars(date: str) -> list[dict[str, object]]:
        calls.append(date)
        return [_bar("72030", 100)] if date == "2026-09-09" else []

    monkeypatch.setattr(rs.jquants, "fetch_all_daily_bars", fake_bars)
    date_str, bars = await rs._walk_back_for_bars(datetime.date(2026, 9, 11))
    assert date_str == "2026-09-09"
    assert len(bars) == 1
    assert calls == ["2026-09-11", "2026-09-10", "2026-09-09"]


async def test_walk_back_raises_when_no_trading_day_found(monkeypatch: pytest.MonkeyPatch) -> None:
    async def always_empty(_date: str) -> list[dict[str, object]]:
        return []

    monkeypatch.setattr(rs.jquants, "fetch_all_daily_bars", always_empty)
    with pytest.raises(JQuantsError):
        await rs._walk_back_for_bars(datetime.date(2026, 9, 11))


async def test_subscription_fallback_retries_at_upper_bound(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_bars(date: str) -> list[dict[str, object]]:
        if date == "2026-09-11":
            raise JQuantsClientError(
                "/equities/bars/daily",
                400,
                body="Your subscription covers the following dates: 2024-01-01 ~ 2026-04-25.",
            )
        return [_bar("72030", 100)]

    monkeypatch.setattr(rs.jquants, "fetch_all_daily_bars", fake_bars)
    date_str, bars = await rs._walk_back_with_subscription_fallback(datetime.date(2026, 9, 11))
    assert date_str == "2026-04-25"
    assert bars


async def test_compute_rankings_end_to_end(monkeypatch: pytest.MonkeyPatch) -> None:
    today_bars = [_bar("72030", 110, 5000), _bar("67580", 90, 8000), _bar("99840", 100, 1000)]
    prev_bars = [_bar("72030", 100), _bar("67580", 100), _bar("99840", 100)]

    async def fake_bars(date: str) -> list[dict[str, object]]:
        # 最初の呼び出し（today 解決）と 2 回目（前日）を日付で分岐。
        return today_bars if date == datetime.date.today().isoformat() else prev_bars

    async def fake_master() -> list[dict[str, object]]:
        return [
            {"Code": "72030", "CoName": "トヨタ自動車"},
            {"Code": "67580", "CoName": "ソニーグループ"},
            {"Code": "99840", "CoName": "ソフトバンクグループ"},
        ]

    monkeypatch.setattr(rs.jquants, "fetch_all_daily_bars", fake_bars)
    monkeypatch.setattr(rs.jquants, "fetch_all_listed_stocks", fake_master)

    result = await rs.get_rankings(limit=2)
    assert result.gainers[0].code == "7203"  # +10%
    assert result.gainers[0].name == "トヨタ自動車"
    assert result.losers[0].code == "6758"  # -10%
    assert result.volume_leaders[0].code == "6758"  # volume 8000
    assert result.market_breadth.advancers == 1
    assert result.market_breadth.decliners == 1


def test_rankings_from_bars_is_pure_and_matches_ordering() -> None:
    """🆕 P37: 2 日分の全銘柄バーからランキングを作る純関数（過去日リプレイが同じ規則で候補プールを再現する）."""
    prev = [_bar("11110", 100.0), _bar("22220", 100.0), _bar("33330", 100.0), _bar("44440", 100.0)]
    today = [
        _bar("11110", 110.0, volume=10),
        _bar("22220", 90.0, volume=5000),
        _bar("33330", 100.0, volume=300),
        _bar("55550", 50.0, volume=9999),  # 前日に存在しない（新規上場）→ 除外
    ]

    out = rs.rankings_from_bars("2021-10-01", today, prev, {"11110": "銘柄A"}, pool_size=2)

    assert out.as_of_date == "2021-10-01"
    assert [e.code for e in out.gainers] == ["1111", "3333"]
    assert [e.code for e in out.losers] == ["2222", "3333"]
    assert [e.code for e in out.volume_leaders] == ["2222", "3333"]
    assert out.gainers[0].name == "銘柄A"
    assert out.gainers[1].name == "33330"  # 名前解決できない銘柄はコード表示
    assert (out.market_breadth.advancers, out.market_breadth.decliners, out.market_breadth.unchanged) == (1, 1, 1)


def test_rankings_from_bars_raises_when_no_entries() -> None:
    with pytest.raises(rs.JQuantsError):
        rs.rankings_from_bars("2021-10-01", [_bar("11110", 100.0)], [], {}, pool_size=5)
