"""業種別トレンド集計サービスの検証（Market Lens から移植）."""

from __future__ import annotations

from collections.abc import Iterator

import pandas as pd
import pytest

from backend.services.data import trend_service as ts
from backend.services.data.jquants_errors import JQuantsError


@pytest.fixture(autouse=True)
def _reset_cache() -> Iterator[None]:
    ts._cache.clear()
    yield
    ts._cache.clear()


def test_group_by_sector_uses_s33_name() -> None:
    stocks: list[dict[str, object]] = [
        {"Code": "72030", "S33Nm": "輸送用機器", "S33": "3700"},
        {"Code": "72010", "S33Nm": "輸送用機器", "S33": "3700"},
        {"Code": "83060", "S33Nm": "銀行業", "S33": "7050"},
    ]
    groups = ts._group_by_sector(stocks)
    assert set(groups) == {"輸送用機器", "銀行業"}
    assert len(groups["輸送用機器"]["stocks"]) == 2


def test_generate_reasoning_mentions_sector_and_return() -> None:
    text = ts._generate_reasoning("輸送用機器", 2.5, 80.0, 5)
    assert "輸送用機器" in text
    assert "+2.5%" in text


async def test_compute_trend_catchup_builds_up_and_down_sectors(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_master() -> list[dict[str, object]]:
        return [
            {"Code": "10010", "CoName": "上昇銘柄A", "S33Nm": "上昇業種", "S33": "1"},
            {"Code": "10020", "CoName": "上昇銘柄B", "S33Nm": "上昇業種", "S33": "1"},
            {"Code": "20010", "CoName": "下降銘柄A", "S33Nm": "下降業種", "S33": "2"},
        ]

    def frame(first: float, last: float) -> pd.DataFrame:
        return pd.DataFrame({"Close": [first, last]}, index=pd.to_datetime(["2026-09-03", "2026-09-10"]))

    async def fake_quotes(code: str, period: str = "2w") -> pd.DataFrame:  # noqa: ARG001
        return {
            "10010": frame(100, 106),
            "10020": frame(100, 104),
            "20010": frame(100, 94),
        }[code]

    monkeypatch.setattr(ts.jquants, "fetch_all_listed_stocks", fake_master)
    monkeypatch.setattr(ts.jquants, "fetch_daily_quotes", fake_quotes)

    result = await ts.get_trend_catchup()
    assert [s.sector_name for s in result.uptrend_sectors] == ["上昇業種"]
    assert [s.sector_name for s in result.downtrend_sectors] == ["下降業種"]
    assert result.uptrend_sectors[0].direction == "up"


async def test_compute_trend_catchup_raises_when_master_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    async def empty_master() -> list[dict[str, object]]:
        return []

    monkeypatch.setattr(ts.jquants, "fetch_all_listed_stocks", empty_master)
    with pytest.raises(JQuantsError):
        await ts.get_trend_catchup()


async def test_single_ticker_failure_is_tolerated(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_master() -> list[dict[str, object]]:
        return [
            {"Code": "10010", "CoName": "OK", "S33Nm": "業種", "S33": "1"},
            {"Code": "10020", "CoName": "NG", "S33Nm": "業種", "S33": "1"},
        ]

    async def fake_quotes(code: str, period: str = "2w") -> pd.DataFrame:  # noqa: ARG001
        if code == "10020":
            raise JQuantsError("boom")
        return pd.DataFrame({"Close": [100.0, 105.0]}, index=pd.to_datetime(["2026-09-03", "2026-09-10"]))

    monkeypatch.setattr(ts.jquants, "fetch_all_listed_stocks", fake_master)
    monkeypatch.setattr(ts.jquants, "fetch_daily_quotes", fake_quotes)

    result = await ts.get_trend_catchup()
    # 1 銘柄失敗しても集計は成立する（+5% の 1 銘柄で上昇業種）。
    assert result.uptrend_sectors and result.uptrend_sectors[0].stock_count == 1
