"""`signal_service.evaluate_holding` / `run_portfolio_monitor` の検証."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from backend.models.portfolio import PortfolioHolding
from backend.services.anthropic_errors import AnthropicRateLimitError
from backend.services.db.notification_db import list_notifications
from backend.services.db.portfolio_db import insert_holding
from backend.services.db.portfolio_signal_db import get_signal, list_signals
from backend.services.db.portfolio_signal_shadow_db import get_shadows_for_signals
from backend.services.gemini_errors import GeminiRateLimitError
from backend.services.portfolio import signal_service as svc

_DEFAULT_LLM: dict[str, object] = {
    "action": "hold",
    "stop_loss_price": 950.0,
    "take_profit_price": 1150.0,
    "confidence": 70.0,
    "reasoning": "堅調に推移",
}

_DEFAULT_GEMINI: dict[str, object] = {
    "action": "hold",
    "stop_loss_price": 960.0,
    "take_profit_price": 1140.0,
    "confidence": 65.0,
    "reasoning": "Gemini 側は中立と判定",
}


class _FakeGemini:
    """`is_configured` を素の属性で持つ GeminiClient スタブ（`test_pick_pipeline._FakeGemini` と同じ形）."""

    def __init__(self, response: object = None, *, configured: bool = True) -> None:
        self.is_configured = configured
        self._response = response if response is not None else dict(_DEFAULT_GEMINI)

    async def propose_portfolio_signal(self, *, symbol: str, prompt: str) -> dict[str, object]:  # noqa: ARG002
        if isinstance(self._response, Exception):
            raise self._response
        return dict(self._response) if isinstance(self._response, dict) else dict(_DEFAULT_GEMINI)


def _holding(**overrides: object) -> PortfolioHolding:
    base: dict[str, object] = {
        "holding_id": "h1",
        "symbol": "7203",
        "company_name": "トヨタ",
        "sector": "輸送用機器",
        "quantity": 100,
        "avg_cost": 1000.0,
        "current_price": 1050.0,
        "current_value": 105_000.0,
        "cost_basis": 100_000.0,
        "gain_loss": 5_000.0,
        "return_pct": 0.05,
        "acquired_at": "2026-01-15",
    }
    base.update(overrides)
    return PortfolioHolding.model_validate(base)


class _FakeLLM:
    def __init__(self, response: object) -> None:
        self._response = response

    async def propose_portfolio_signal(self, *, symbol: str, prompt: str) -> dict[str, object]:  # noqa: ARG002
        if isinstance(self._response, Exception):
            raise self._response
        return dict(self._response) if isinstance(self._response, dict) else dict(_DEFAULT_LLM)


@pytest.fixture(autouse=True)
def _stub_price_data(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_get_stock_data(_symbol: str, period: str = "1y") -> pd.DataFrame:  # noqa: ARG001
        return pd.DataFrame(
            {
                "High": [1060.0] * 20,
                "Low": [1040.0] * 20,
                "Close": [1050.0] * 20,
            }
        )

    monkeypatch.setattr(svc, "get_stock_data", fake_get_stock_data)


async def test_evaluate_holding_hold_action_persists_signal(migrated_db: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(svc, "anthropic_client", _FakeLLM(_DEFAULT_LLM))

    signal_id = await svc.evaluate_holding(_holding())

    assert signal_id is not None
    row = await get_signal(signal_id)
    assert row is not None
    assert row["action"] == "hold"
    assert row["entry"] is None
    assert row["status"] == "proposed"


async def test_evaluate_holding_hold_action_does_not_notify(migrated_db: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(svc, "anthropic_client", _FakeLLM(_DEFAULT_LLM))

    await svc.evaluate_holding(_holding())

    assert await list_notifications() == []


async def test_evaluate_holding_add_action_persists_entry(migrated_db: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        svc,
        "anthropic_client",
        _FakeLLM(
            {
                "action": "add",
                "entry": 1055.0,
                "stop_loss_price": 950.0,
                "take_profit_price": 1200.0,
                "confidence": 65.0,
                "reasoning": "押し目買い増し",
            }
        ),
    )

    signal_id = await svc.evaluate_holding(_holding())

    assert signal_id is not None
    row = await get_signal(signal_id)
    assert row is not None
    assert row["action"] == "add"
    assert row["entry"] == pytest.approx(1055.0)

    notifications = await list_notifications()
    assert len(notifications) == 1
    assert notifications[0]["ticker"] == "7203"
    assert notifications[0]["kind"] == "add"


async def test_evaluate_holding_returns_none_when_current_price_missing(migrated_db: Path) -> None:
    signal_id = await svc.evaluate_holding(_holding(current_price=None))
    assert signal_id is None
    assert await list_signals() == []


async def test_evaluate_holding_returns_none_on_llm_error(migrated_db: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(svc, "anthropic_client", _FakeLLM(AnthropicRateLimitError("portfolio_signal")))

    signal_id = await svc.evaluate_holding(_holding())

    assert signal_id is None
    assert await list_signals() == []


async def test_evaluate_holding_rejects_invalid_action(migrated_db: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(svc, "anthropic_client", _FakeLLM({**_DEFAULT_LLM, "action": "sell_everything"}))

    signal_id = await svc.evaluate_holding(_holding())

    assert signal_id is None
    assert await list_signals() == []


async def test_evaluate_holding_rejects_malformed_numbers(migrated_db: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(svc, "anthropic_client", _FakeLLM({**_DEFAULT_LLM, "confidence": "not-a-number"}))

    signal_id = await svc.evaluate_holding(_holding())

    assert signal_id is None
    assert await list_signals() == []


async def test_evaluate_holding_rejects_inconsistent_bracket(
    migrated_db: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # stop >= current_price は finalize_bracket が拒否する不整合。
    monkeypatch.setattr(
        svc,
        "anthropic_client",
        _FakeLLM({**_DEFAULT_LLM, "stop_loss_price": 2000.0, "take_profit_price": 2500.0}),
    )

    signal_id = await svc.evaluate_holding(_holding())

    assert signal_id is None
    assert await list_signals() == []


async def test_evaluate_holding_gemini_not_configured_records_no_shadow(
    migrated_db: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """既定（Gemini 未設定）では shadow 判定は記録されない（公式判定には影響しない）."""
    monkeypatch.setattr(svc, "anthropic_client", _FakeLLM(_DEFAULT_LLM))
    monkeypatch.setattr(svc, "gemini_client", _FakeGemini(configured=False))

    signal_id = await svc.evaluate_holding(_holding())

    assert signal_id is not None
    shadows = await get_shadows_for_signals([signal_id])
    assert shadows == {}


async def test_evaluate_holding_gemini_configured_records_shadow(
    migrated_db: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Gemini 設定済み・正常応答 → 公式判定と併せて shadow 判定が1件記録される."""
    monkeypatch.setattr(svc, "anthropic_client", _FakeLLM(_DEFAULT_LLM))
    monkeypatch.setattr(svc, "gemini_client", _FakeGemini())

    signal_id = await svc.evaluate_holding(_holding())

    assert signal_id is not None
    shadows = await get_shadows_for_signals([signal_id])
    assert signal_id in shadows
    shadow = shadows[signal_id]
    assert shadow["action"] == "hold"
    assert shadow["reasoning"] == "Gemini 側は中立と判定"


async def test_evaluate_holding_gemini_error_still_persists_official_signal(
    migrated_db: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Gemini 呼び出し失敗はフェイルソフト — 公式判定の記録には一切影響しない."""
    monkeypatch.setattr(svc, "anthropic_client", _FakeLLM(_DEFAULT_LLM))
    monkeypatch.setattr(svc, "gemini_client", _FakeGemini(GeminiRateLimitError("portfolio_signal_gemini")))

    signal_id = await svc.evaluate_holding(_holding())

    assert signal_id is not None
    shadows = await get_shadows_for_signals([signal_id])
    assert shadows == {}


async def test_evaluate_holding_gemini_invalid_action_records_no_shadow(
    migrated_db: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(svc, "anthropic_client", _FakeLLM(_DEFAULT_LLM))
    monkeypatch.setattr(svc, "gemini_client", _FakeGemini({**_DEFAULT_GEMINI, "action": "sell_everything"}))

    signal_id = await svc.evaluate_holding(_holding())

    assert signal_id is not None
    shadows = await get_shadows_for_signals([signal_id])
    assert shadows == {}


async def test_run_portfolio_monitor_evaluates_all_holdings(migrated_db: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(svc, "anthropic_client", _FakeLLM(_DEFAULT_LLM))

    def fake_get_company_info(_symbol: str) -> dict[str, str | None]:
        return {"name": "A", "sector": "輸送用機器"}

    def fake_fetch_stock_data(_symbol: str, period: str, interval: str) -> pd.DataFrame:  # noqa: ARG001
        return pd.DataFrame({"Close": [1000.0, 1050.0]})

    from backend.services.data import quote_service
    from backend.services.portfolio import portfolio_service as psvc

    monkeypatch.setattr(psvc, "get_company_info", fake_get_company_info)
    # 🔧 P13: 価格取得は `quote_service.fetch_quote` へ委譲されたため、そちらをパッチする。
    monkeypatch.setattr(quote_service, "fetch_stock_data", fake_fetch_stock_data)

    await insert_holding(symbol="7203", quantity=100, avg_cost=1000.0, acquired_at="2026-01-15")
    await insert_holding(symbol="6758", quantity=50, avg_cost=2000.0, acquired_at="2026-01-16")

    signal_ids = await svc.run_portfolio_monitor()

    assert len(signal_ids) == 2
    rows = await list_signals()
    assert {r["symbol"] for r in rows} == {"7203", "6758"}
