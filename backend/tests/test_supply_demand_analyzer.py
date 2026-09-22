"""需給分析サービス（週末信用取引残高）の検証.

外部 API は叩かず ``jquants.fetch_weekly_margin_interest`` をモックし、比率計算・分類・
フェイルソフト分岐（未設定/403/データ無し/売り残ゼロ）・プロンプト用ブロック整形を確認する。
"""

from __future__ import annotations

import pytest

from backend.models.jquants_raw import RawWeeklyMarginInterest
from backend.services.data import jquants_client as jq
from backend.services.data.jquants_errors import JQuantsClientError
from backend.services.scoring import supply_demand_analyzer as sda


def _record(date: str, *, long_volume: float | None, short_volume: float | None) -> RawWeeklyMarginInterest:
    return RawWeeklyMarginInterest.model_validate(
        {"Date": date, "Code": "72030", "LongVol": long_volume, "ShrtVol": short_volume}
    )


def test_classify_margin_ratio_long_heavy() -> None:
    assert sda.classify_margin_ratio(6.0) == "long_heavy"
    assert sda.classify_margin_ratio(10.0) == "long_heavy"


def test_classify_margin_ratio_short_heavy() -> None:
    assert sda.classify_margin_ratio(1.0) == "short_heavy"
    assert sda.classify_margin_ratio(0.2) == "short_heavy"


def test_classify_margin_ratio_balanced() -> None:
    assert sda.classify_margin_ratio(3.0) == "balanced"


def _configure_api_key(monkeypatch: pytest.MonkeyPatch, *, key: str = "k") -> None:
    monkeypatch.setattr(jq, "settings", jq.settings.model_copy(update={"jquants_api_key": key}))


async def test_get_supply_demand_data_not_configured(monkeypatch: pytest.MonkeyPatch) -> None:
    _configure_api_key(monkeypatch, key="")
    assert await sda.get_supply_demand_data("7203") is None


async def test_get_supply_demand_data_returns_none_on_client_error(monkeypatch: pytest.MonkeyPatch) -> None:
    _configure_api_key(monkeypatch)

    async def fake_fetch(_code: str) -> list[RawWeeklyMarginInterest]:
        raise JQuantsClientError("/markets/margin-interest", 403, "not available on your subscription")

    monkeypatch.setattr(sda.jquants, "fetch_weekly_margin_interest", fake_fetch)
    assert await sda.get_supply_demand_data("7203") is None


async def test_get_supply_demand_data_returns_none_when_no_records(monkeypatch: pytest.MonkeyPatch) -> None:
    _configure_api_key(monkeypatch)

    async def fake_fetch(_code: str) -> list[RawWeeklyMarginInterest]:
        return []

    monkeypatch.setattr(sda.jquants, "fetch_weekly_margin_interest", fake_fetch)
    assert await sda.get_supply_demand_data("7203") is None


async def test_get_supply_demand_data_returns_none_when_short_volume_zero(monkeypatch: pytest.MonkeyPatch) -> None:
    _configure_api_key(monkeypatch)

    async def fake_fetch(_code: str) -> list[RawWeeklyMarginInterest]:
        return [_record("2026-09-18", long_volume=1000.0, short_volume=0.0)]

    monkeypatch.setattr(sda.jquants, "fetch_weekly_margin_interest", fake_fetch)
    assert await sda.get_supply_demand_data("7203") is None


async def test_get_supply_demand_data_computes_ratio_and_classification(monkeypatch: pytest.MonkeyPatch) -> None:
    _configure_api_key(monkeypatch)

    async def fake_fetch(_code: str) -> list[RawWeeklyMarginInterest]:
        return [
            _record("2026-09-18", long_volume=6500.0, short_volume=1000.0),
            _record("2026-09-11", long_volume=6000.0, short_volume=1200.0),
        ]

    monkeypatch.setattr(sda.jquants, "fetch_weekly_margin_interest", fake_fetch)
    data = await sda.get_supply_demand_data("7203")

    assert data is not None
    assert data["as_of"] == "2026-09-18"
    assert data["margin_ratio"] == 6.5
    assert data["classification"] == "long_heavy"
    assert data["margin_ratio_prev"] == 5.0
    # 空売り残は 1200 -> 1000 で -16.67%
    assert data["short_ratio_change_wow"] == pytest.approx(-0.1667, abs=1e-4)


async def test_get_supply_demand_data_without_prior_week(monkeypatch: pytest.MonkeyPatch) -> None:
    _configure_api_key(monkeypatch)

    async def fake_fetch(_code: str) -> list[RawWeeklyMarginInterest]:
        return [_record("2026-09-18", long_volume=800.0, short_volume=1000.0)]

    monkeypatch.setattr(sda.jquants, "fetch_weekly_margin_interest", fake_fetch)
    data = await sda.get_supply_demand_data("7203")

    assert data is not None
    assert data["classification"] == "short_heavy"
    assert data["margin_ratio_prev"] is None
    assert data["short_ratio_change_wow"] is None


def test_render_supply_demand_block_none_when_no_data() -> None:
    assert sda.render_supply_demand_block(None) is None


def test_render_supply_demand_block_includes_ratio_and_classification_label() -> None:
    block = sda.render_supply_demand_block(
        {
            "as_of": "2026-09-18",
            "long_volume": 6500.0,
            "short_volume": 1000.0,
            "margin_ratio": 6.5,
            "margin_ratio_prev": 5.0,
            "short_ratio_change_wow": -0.1667,
            "classification": "long_heavy",
        }
    )
    assert block is not None
    assert "6.50倍" in block
    assert "買い長残優勢" in block
    assert "前週の信用倍率: 5.00倍" in block
    assert "-16.7%" in block
