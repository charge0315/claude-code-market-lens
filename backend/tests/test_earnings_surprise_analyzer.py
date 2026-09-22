"""決算サプライズ・予想修正モメンタム分析サービスの検証.

外部 API は叩かず ``jquants.fetch_statements`` をモックし、サプライズ/修正率の計算・分類・
FY またぎでの `None` フォールバック・フェイルソフト分岐・プロンプト用ブロック整形を確認する。
"""

from __future__ import annotations

from typing import cast

import pytest

from backend.models.jquants_raw import RawStatement
from backend.services.data import jquants_client as jq
from backend.services.data.jquants_errors import JQuantsClientError
from backend.services.scoring import earnings_surprise_analyzer as esa


def _record(
    *,
    disclosed_date: str,
    fiscal_year_end: str,
    period_type: str,
    net_sales: float | None = None,
    operating_profit: float | None = None,
    profit: float | None = None,
    eps: float | None = None,
    forecast_net_sales: float | None = None,
    forecast_operating_profit: float | None = None,
    forecast_profit: float | None = None,
    forecast_eps: float | None = None,
) -> RawStatement:
    return RawStatement.model_validate(
        {
            "DiscDate": disclosed_date,
            "CurFYEn": fiscal_year_end,
            "CurPerType": period_type,
            "Sales": net_sales,
            "OP": operating_profit,
            "NP": profit,
            "EPS": eps,
            "FSales": forecast_net_sales,
            "FOP": forecast_operating_profit,
            "FNP": forecast_profit,
            "FEPS": forecast_eps,
        }
    )


def test_classify_revision_upward() -> None:
    assert esa.classify_revision(0.05) == "upward"
    assert esa.classify_revision(0.01) == "upward"


def test_classify_revision_downward() -> None:
    assert esa.classify_revision(-0.05) == "downward"
    assert esa.classify_revision(-0.01) == "downward"


def test_classify_revision_unchanged_within_deadband() -> None:
    assert esa.classify_revision(0.005) == "unchanged"
    assert esa.classify_revision(-0.005) == "unchanged"


def _configure_api_key(monkeypatch: pytest.MonkeyPatch, *, key: str = "k") -> None:
    monkeypatch.setattr(jq, "settings", jq.settings.model_copy(update={"jquants_api_key": key}))


async def test_get_earnings_surprise_data_not_configured(monkeypatch: pytest.MonkeyPatch) -> None:
    _configure_api_key(monkeypatch, key="")
    assert await esa.get_earnings_surprise_data("7203") is None


async def test_get_earnings_surprise_data_returns_none_on_client_error(monkeypatch: pytest.MonkeyPatch) -> None:
    _configure_api_key(monkeypatch)

    async def fake_fetch(_code: str) -> list[RawStatement]:
        raise JQuantsClientError("/fins/summary", 403, "not available on your subscription")

    monkeypatch.setattr(esa.jquants, "fetch_statements", fake_fetch)
    assert await esa.get_earnings_surprise_data("7203") is None


async def test_get_earnings_surprise_data_returns_none_when_insufficient_records(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _configure_api_key(monkeypatch)

    async def fake_fetch(_code: str) -> list[RawStatement]:
        return [_record(disclosed_date="2026-05-10", fiscal_year_end="2026-03-31", period_type="FY")]

    monkeypatch.setattr(esa.jquants, "fetch_statements", fake_fetch)
    assert await esa.get_earnings_surprise_data("7203") is None


async def test_get_earnings_surprise_data_computes_surprise_at_fy_close(monkeypatch: pytest.MonkeyPatch) -> None:
    _configure_api_key(monkeypatch)

    async def fake_fetch(_code: str) -> list[RawStatement]:
        return [
            _record(
                disclosed_date="2026-05-10",
                fiscal_year_end="2026-03-31",
                period_type="FY",
                net_sales=48_000_000.0,
                operating_profit=5_500_000.0,
                profit=4_200_000.0,
                eps=400.0,
            ),
            _record(
                disclosed_date="2026-02-05",
                fiscal_year_end="2026-03-31",
                period_type="3Q",
                forecast_net_sales=45_000_000.0,
                forecast_operating_profit=5_000_000.0,
                forecast_profit=4_000_000.0,
                forecast_eps=380.0,
            ),
        ]

    monkeypatch.setattr(esa.jquants, "fetch_statements", fake_fetch)
    data = await esa.get_earnings_surprise_data("7203")

    assert data is not None
    assert data["period_type"] == "FY"
    assert data["surprise"] is not None
    surprise = cast("dict[str, dict[str, object]]", data["surprise"])
    # 営業利益: 5,500,000 実績 vs 5,000,000 予想 -> +10%
    assert surprise["operating_profit"]["surprise_rate"] == pytest.approx(0.10, abs=1e-4)
    assert surprise["operating_profit"]["actual"] == 5_500_000.0


async def test_get_earnings_surprise_data_surprise_is_none_for_non_fy_disclosure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _configure_api_key(monkeypatch)

    async def fake_fetch(_code: str) -> list[RawStatement]:
        return [
            _record(
                disclosed_date="2026-02-05",
                fiscal_year_end="2026-03-31",
                period_type="3Q",
                net_sales=35_000_000.0,
                forecast_operating_profit=5_200_000.0,
            ),
            _record(
                disclosed_date="2025-11-06",
                fiscal_year_end="2026-03-31",
                period_type="2Q",
                forecast_operating_profit=5_000_000.0,
            ),
        ]

    monkeypatch.setattr(esa.jquants, "fetch_statements", fake_fetch)
    data = await esa.get_earnings_surprise_data("7203")

    assert data is not None
    assert data["surprise"] is None
    # 予想修正モメンタムは四半期間でも計算可能: 5,200,000 vs 5,000,000 -> +4%
    assert data["revision"] is not None
    revision = cast("dict[str, dict[str, object]]", data["revision"])
    assert revision["forecast_operating_profit"]["classification"] == "upward"
    assert revision["forecast_operating_profit"]["revision_rate"] == pytest.approx(0.04, abs=1e-4)


async def test_get_earnings_surprise_data_revision_is_none_across_fiscal_year_boundary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _configure_api_key(monkeypatch)

    async def fake_fetch(_code: str) -> list[RawStatement]:
        return [
            _record(
                disclosed_date="2026-08-07",
                fiscal_year_end="2027-03-31",
                period_type="1Q",
                forecast_operating_profit=3_200_000.0,
            ),
            _record(
                disclosed_date="2026-05-08",
                fiscal_year_end="2026-03-31",
                period_type="FY",
                operating_profit=5_500_000.0,
            ),
        ]

    monkeypatch.setattr(esa.jquants, "fetch_statements", fake_fetch)
    data = await esa.get_earnings_surprise_data("7203")

    # FY またぎ（fiscal_year_end 不一致）のため surprise/revision いずれも算出せず None に畳まれる
    assert data is None


def test_render_earnings_surprise_block_none_when_no_data() -> None:
    assert esa.render_earnings_surprise_block(None) is None


def test_render_earnings_surprise_block_includes_surprise_and_revision() -> None:
    block = esa.render_earnings_surprise_block(
        {
            "as_of": "2026-05-10",
            "fiscal_year_end": "2026-03-31",
            "period_type": "FY",
            "surprise": {
                "operating_profit": {
                    "label": "営業利益",
                    "actual": 5_500_000.0,
                    "prior_forecast": 5_000_000.0,
                    "surprise_rate": 0.10,
                }
            },
            "revision": {
                "forecast_operating_profit": {
                    "label": "営業利益",
                    "current_forecast": 5_000_000.0,
                    "prior_forecast": 4_800_000.0,
                    "revision_rate": 0.0417,
                    "classification": "upward",
                }
            },
        }
    )
    assert block is not None
    assert "決算サプライズ" in block
    assert "+10.0%" in block
    assert "上方修正" in block
