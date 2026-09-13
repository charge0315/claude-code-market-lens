"""ポートフォリオ API（`routers/portfolio.py`）の検証."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest
from httpx import ASGITransport, AsyncClient

from backend.services.data import quote_service
from backend.services.db.portfolio_signal_db import insert_signal
from backend.services.portfolio import portfolio_service as psvc


@pytest.fixture(autouse=True)
def _stub_fetchers(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_get_company_info(_symbol: str) -> dict[str, str | None]:
        return {"name": "会社名", "sector": "輸送用機器"}

    def fake_fetch_stock_data(_symbol: str, period: str, interval: str) -> pd.DataFrame:  # noqa: ARG001
        return pd.DataFrame({"Close": [1000.0, 1010.0]})

    monkeypatch.setattr(psvc, "get_company_info", fake_get_company_info)
    # 🔧 P13: 価格取得は `quote_service.fetch_quote` へ委譲されたため、そちらをパッチする。
    monkeypatch.setattr(quote_service, "fetch_stock_data", fake_fetch_stock_data)


async def test_portfolio_crud_and_get_flow(migrated_db: Path) -> None:
    from backend.main import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        empty = (await client.get("/api/portfolio")).json()
        assert empty["success"] is True
        assert empty["data"]["holding_count"] == 0

        add_res = await client.post(
            "/api/portfolio/holdings",
            json={"symbol": "7203", "quantity": 100, "avg_cost": 1000.0, "acquired_at": "2026-01-15"},
        )
        assert add_res.status_code == 201
        holding_id = add_res.json()["data"]["holding_id"]

        summary = (await client.get("/api/portfolio")).json()
        assert summary["data"]["holding_count"] == 1
        assert summary["data"]["holdings"][0]["symbol"] == "7203"
        assert summary["data"]["holdings"][0]["current_price"] == 1010.0

        update_res = await client.put(
            f"/api/portfolio/holdings/{holding_id}", json={"quantity": 200, "avg_cost": 1100.0}
        )
        assert update_res.json()["success"] is True

        summary2 = (await client.get("/api/portfolio")).json()
        assert summary2["data"]["holdings"][0]["quantity"] == 200

        delete_res = await client.delete(f"/api/portfolio/holdings/{holding_id}")
        assert delete_res.json()["success"] is True

        summary3 = (await client.get("/api/portfolio")).json()
        assert summary3["data"]["holding_count"] == 0


async def test_add_holding_rejects_non_positive_quantity(migrated_db: Path) -> None:
    from backend.main import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        res = await client.post(
            "/api/portfolio/holdings",
            json={"symbol": "7203", "quantity": 0, "avg_cost": 1000.0, "acquired_at": "2026-01-15"},
        )
    assert res.status_code == 422


async def test_add_duplicate_lot_returns_conflict(migrated_db: Path) -> None:
    from backend.main import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        payload = {"symbol": "7203", "quantity": 100, "avg_cost": 1000.0, "acquired_at": "2026-01-15"}
        first = await client.post("/api/portfolio/holdings", json=payload)
        assert first.status_code == 201

        second = await client.post("/api/portfolio/holdings", json=payload)
    assert second.status_code == 409


async def test_update_unknown_holding_returns_404(migrated_db: Path) -> None:
    from backend.main import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        res = await client.put("/api/portfolio/holdings/does-not-exist", json={"quantity": 1, "avg_cost": 1.0})
    assert res.status_code == 404


async def test_delete_unknown_holding_returns_404(migrated_db: Path) -> None:
    from backend.main import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        res = await client.delete("/api/portfolio/holdings/does-not-exist")
    assert res.status_code == 404


async def test_sell_holding_full_quantity_deletes_lot_and_records_history(migrated_db: Path) -> None:
    from backend.main import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        add_res = await client.post(
            "/api/portfolio/holdings",
            json={"symbol": "7203", "quantity": 100, "avg_cost": 1000.0, "acquired_at": "2026-01-15"},
        )
        holding_id = add_res.json()["data"]["holding_id"]

        sell_res = await client.post(
            f"/api/portfolio/holdings/{holding_id}/sell",
            json={"quantity": 100, "sell_price": 1200.0, "sold_at": "2026-09-13"},
        )
        assert sell_res.status_code == 200
        sold = sell_res.json()["data"]
        assert sold["realized_pnl"] == pytest.approx(20_000.0)
        assert sold["symbol"] == "7203"

        # 全量売却なのでロット自体が消える。
        summary = (await client.get("/api/portfolio")).json()
        assert summary["data"]["holding_count"] == 0

        history = (await client.get("/api/portfolio/sell-history")).json()
        assert len(history["data"]) == 1
        assert history["data"][0]["realized_pnl"] == pytest.approx(20_000.0)


async def test_sell_holding_partial_quantity_reduces_lot(migrated_db: Path) -> None:
    from backend.main import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        add_res = await client.post(
            "/api/portfolio/holdings",
            json={"symbol": "7203", "quantity": 100, "avg_cost": 1000.0, "acquired_at": "2026-01-15"},
        )
        holding_id = add_res.json()["data"]["holding_id"]

        sell_res = await client.post(
            f"/api/portfolio/holdings/{holding_id}/sell",
            json={"quantity": 40, "sell_price": 1100.0, "sold_at": "2026-09-13"},
        )
        assert sell_res.json()["data"]["realized_pnl"] == pytest.approx(4_000.0)

        summary = (await client.get("/api/portfolio")).json()
        assert summary["data"]["holding_count"] == 1
        assert summary["data"]["holdings"][0]["quantity"] == 60


async def test_sell_holding_more_than_owned_returns_422(migrated_db: Path) -> None:
    from backend.main import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        add_res = await client.post(
            "/api/portfolio/holdings",
            json={"symbol": "7203", "quantity": 10, "avg_cost": 1000.0, "acquired_at": "2026-01-15"},
        )
        holding_id = add_res.json()["data"]["holding_id"]

        res = await client.post(
            f"/api/portfolio/holdings/{holding_id}/sell",
            json={"quantity": 11, "sell_price": 1000.0, "sold_at": "2026-09-13"},
        )
    assert res.status_code == 422


async def test_sell_unknown_holding_returns_404(migrated_db: Path) -> None:
    from backend.main import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        res = await client.post(
            "/api/portfolio/holdings/does-not-exist/sell",
            json={"quantity": 1, "sell_price": 1000.0, "sold_at": "2026-09-13"},
        )
    assert res.status_code == 404


async def test_sell_history_endpoint_returns_empty_by_default(migrated_db: Path) -> None:
    from backend.main import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        res = await client.get("/api/portfolio/sell-history")
    assert res.json()["data"] == []


async def test_risk_endpoint_returns_report(migrated_db: Path) -> None:
    from backend.main import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        res = await client.get("/api/portfolio/risk")
    body = res.json()
    assert body["success"] is True
    assert body["data"]["analyzed_count"] == 0
    assert body["data"]["message"] == "保有銘柄がありません"


async def test_signals_list_and_filter_by_status(migrated_db: Path) -> None:
    proposed_id = await insert_signal(
        symbol="7203", action="hold", stop=900.0, target=1100.0, confidence=60.0, rationale="x"
    )
    from backend.main import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        all_res = await client.get("/api/portfolio/signals")
        assert len(all_res.json()["data"]) == 1
        assert all_res.json()["data"][0]["signal_id"] == proposed_id

        filtered = await client.get("/api/portfolio/signals?status=approved")
        assert filtered.json()["data"] == []


async def test_signal_approve_then_report_fill_flow(migrated_db: Path) -> None:
    signal_id = await insert_signal(
        symbol="7203", action="trim", stop=900.0, target=1100.0, confidence=60.0, rationale="x"
    )
    from backend.main import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        approve_res = await client.post(f"/api/portfolio/signals/{signal_id}/approve")
        assert approve_res.json()["data"]["status"] == "approved"

        fill_res = await client.post(
            f"/api/portfolio/signals/{signal_id}/report-fill",
            json={"executed_price": 1050.0, "executed_quantity": 50, "executed_at": "2026-06-01T10:00:00+09:00"},
        )
        assert fill_res.json()["data"]["status"] == "executed"

        signals = (await client.get("/api/portfolio/signals")).json()["data"]
        assert signals[0]["status"] == "executed"
        assert signals[0]["fill_report"] is not None


async def test_signal_reject_flow(migrated_db: Path) -> None:
    signal_id = await insert_signal(
        symbol="7203", action="stop_loss", stop=900.0, target=1100.0, confidence=60.0, rationale="x"
    )
    from backend.main import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        res = await client.post(f"/api/portfolio/signals/{signal_id}/reject")
    assert res.json()["data"]["status"] == "rejected"


async def test_signal_approve_unknown_returns_404(migrated_db: Path) -> None:
    from backend.main import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        res = await client.post("/api/portfolio/signals/does-not-exist/approve")
    assert res.status_code == 404


async def test_signal_approve_twice_returns_conflict(migrated_db: Path) -> None:
    signal_id = await insert_signal(
        symbol="7203", action="hold", stop=900.0, target=1100.0, confidence=60.0, rationale="x"
    )
    from backend.main import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        first = await client.post(f"/api/portfolio/signals/{signal_id}/approve")
        assert first.status_code == 200
        second = await client.post(f"/api/portfolio/signals/{signal_id}/approve")
    assert second.status_code == 409


async def test_report_fill_before_approval_returns_conflict(migrated_db: Path) -> None:
    signal_id = await insert_signal(
        symbol="7203", action="trim", stop=900.0, target=1100.0, confidence=60.0, rationale="x"
    )
    from backend.main import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        res = await client.post(
            f"/api/portfolio/signals/{signal_id}/report-fill",
            json={"executed_price": 1000.0, "executed_quantity": 10, "executed_at": "2026-06-01T10:00:00+09:00"},
        )
    assert res.status_code == 409


async def test_signals_run_endpoint_evaluates_holdings(migrated_db: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from backend.services.db.portfolio_db import insert_holding
    from backend.services.portfolio import signal_service as ssvc

    class _FakeLLM:
        async def propose_portfolio_signal(self, *, symbol: str, prompt: str) -> dict[str, object]:  # noqa: ARG002
            return {
                "action": "hold",
                "stop_loss_price": 950.0,
                "take_profit_price": 1150.0,
                "confidence": 70.0,
                "reasoning": "堅調",
            }

    monkeypatch.setattr(ssvc, "anthropic_client", _FakeLLM())
    await insert_holding(symbol="7203", quantity=100, avg_cost=1000.0, acquired_at="2026-01-15")

    from backend.main import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        res = await client.post("/api/portfolio/signals/run")
    body = res.json()
    assert body["success"] is True
    assert body["data"]["count"] == 1


async def test_eod_review_endpoint_returns_null_when_none_generated_yet(migrated_db: Path) -> None:
    from backend.main import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        res = await client.get("/api/portfolio/eod-review")
    body = res.json()
    assert body["success"] is True
    assert body["data"] is None


async def test_eod_review_run_endpoint_generates_and_is_idempotent(migrated_db: Path) -> None:
    from backend.main import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        first = await client.post("/api/portfolio/eod-review/run")
        assert first.json()["data"]["summary"] == "本日は判定がありませんでした。"

        latest = await client.get("/api/portfolio/eod-review")
        assert latest.json()["data"]["summary"] == "本日は判定がありませんでした。"

        second = await client.post("/api/portfolio/eod-review/run")
        assert second.json()["data"]["created_at"] == first.json()["data"]["created_at"]
