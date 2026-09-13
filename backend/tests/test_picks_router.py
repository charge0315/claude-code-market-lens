"""ピック API の検証（envelope・3 値必須・run 経路）."""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from backend.models.pick import LedgerEntry, PickRunResult, SubScores
from backend.routers import picks as picks_router_module
from backend.services.db.shadow_prediction_db import insert_shadow_prediction
from backend.services.ledger import prediction_ledger as pl
from backend.services.picks import gemini_picks as gp


@pytest.fixture(autouse=True)
def _no_live_quotes(monkeypatch: pytest.MonkeyPatch) -> None:
    """🆕 P13: 現在値取得（ライブ、yfinance）をテストでは決定的にする（既定は取得失敗扱い）."""

    async def fake_fetch_quote(_symbol: str) -> tuple[float | None, float | None]:
        return None, None

    async def fake_fetch_quote_with_spark(_symbol: str) -> tuple[float | None, float | None, list[float]]:
        return None, None, []

    monkeypatch.setattr(pl, "fetch_quote_with_spark", fake_fetch_quote_with_spark)
    monkeypatch.setattr(gp, "fetch_quote_with_spark", fake_fetch_quote_with_spark)
    monkeypatch.setattr(picks_router_module, "fetch_quote", fake_fetch_quote)


@pytest_asyncio.fixture
async def client(migrated_db: Path) -> AsyncIterator[AsyncClient]:
    from backend.main import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac


def _entry(pick_id: str, horizon: str, symbol: str) -> LedgerEntry:
    return LedgerEntry(
        pick_id=pick_id,
        run_id="r1",
        issued_at="2026-09-11T08:50:00+09:00",
        horizon_type=horizon,
        symbol=symbol,
        direction="bullish",
        entry=1002.0,
        stop=985.0,
        target=1050.0,
        sub_scores=SubScores(technical=60, trend=55, fundamental=52, sentiment=50),
        composite_score=60.0,
        concordance=0.67,
        confidence_raw=70.0,
        confidence=72.0,
        confidence_bucket="high",
        feature_snapshot={"atr_14": 20.0},
        rationale_struct={},
        rationale_text="反発余地",
        model_version="baseline-2026-09-11",
        source_contributions={"technical": {"weight_share": 0.6}},
        created_at="2026-09-11T08:50:01+09:00",
    )


async def test_list_mid_term_returns_envelope_with_three_values(client: AsyncClient) -> None:
    await pl.insert_pick(_entry("p1", "mid_term", "7203"))
    await pl.insert_pick(_entry("s1", "short_term", "6758"))

    res = await client.get("/api/picks/mid-term")
    assert res.status_code == 200
    body = res.json()
    assert body["success"] is True
    assert [p["symbol"] for p in body["data"]] == ["7203"]
    pick = body["data"][0]
    for k in ("entry", "stop", "target", "confidence", "confidence_bucket"):
        assert k in pick
    assert pick["stop"] < pick["entry"] < pick["target"]


async def test_list_mid_term_dedupes_repeated_runs_keeping_latest(client: AsyncClient) -> None:
    """beat + 手動 run が同日に重複起動すると同一銘柄が複数台帳化されるが、一覧では最新 1 件のみ表示する."""
    older = _entry("p1", "mid_term", "7203")
    newer = older.model_copy(
        update={"pick_id": "p2", "issued_at": "2026-09-11T09:30:00+09:00", "composite_score": 40.0}
    )
    await pl.insert_pick(older)
    await pl.insert_pick(newer)

    res = await client.get("/api/picks/mid-term")
    body = res.json()
    assert [p["symbol"] for p in body["data"]] == ["7203"]
    assert body["data"][0]["pick_id"] == "p2"


async def test_list_gemini_returns_shadow_predictions(client: AsyncClient) -> None:

    await insert_shadow_prediction(
        pick_id=None,
        run_id="run-1",
        challenger_version="gemini:gemini-2.5-pro",
        symbol="7203",
        horizon_type="mid_term",
        direction="bullish",
        entry=1005.0,
        stop=960.0,
        target=1105.0,
        confidence_raw=65.0,
        confidence=65.0,
        payload={"reasoning": "テスト根拠"},
    )

    res = await client.get("/api/picks/gemini")
    assert res.status_code == 200
    body = res.json()
    assert body["success"] is True
    assert len(body["data"]) == 1
    row = body["data"][0]
    assert row["symbol"] == "7203"
    assert row["challenger_version"] == "gemini:gemini-2.5-pro"
    assert row["reasoning"] == "テスト根拠"


async def test_list_gemini_filters_by_horizon_type(client: AsyncClient) -> None:

    await insert_shadow_prediction(
        pick_id=None,
        run_id="run-mid",
        challenger_version="gemini:gemini-2.5-pro",
        symbol="7203",
        horizon_type="mid_term",
        direction="bullish",
        entry=1000.0,
        stop=950.0,
        target=1100.0,
        confidence_raw=60.0,
        confidence=60.0,
        payload={},
    )
    await insert_shadow_prediction(
        pick_id=None,
        run_id="run-short",
        challenger_version="gemini:gemini-2.5-pro",
        symbol="9984",
        horizon_type="short_term",
        direction="bearish",
        entry=500.0,
        stop=520.0,
        target=470.0,
        confidence_raw=55.0,
        confidence=55.0,
        payload={},
    )

    res = await client.get("/api/picks/gemini", params={"horizon_type": "short_term"})
    body = res.json()
    assert [r["symbol"] for r in body["data"]] == ["9984"]


async def test_get_pick_detail_omits_feature_snapshot(client: AsyncClient) -> None:
    await pl.insert_pick(_entry("p1", "mid_term", "7203"))
    res = await client.get("/api/picks/p1")
    body = res.json()
    assert body["success"] is True
    assert "feature_snapshot" not in body["data"]
    assert body["data"]["symbol"] == "7203"

    missing = await client.get("/api/picks/nope")
    assert missing.json()["success"] is False


async def test_get_pick_detail_includes_live_quote(client: AsyncClient, monkeypatch: pytest.MonkeyPatch) -> None:
    """🆕 P13: current_price/change_pct はライブ値（取得できれば非 None、失敗すれば None）."""

    async def fake_fetch_quote(_symbol: str) -> tuple[float | None, float | None]:
        return 1020.0, 1000.0

    monkeypatch.setattr(picks_router_module, "fetch_quote", fake_fetch_quote)
    await pl.insert_pick(_entry("p1", "mid_term", "7203"))

    res = await client.get("/api/picks/p1")
    data = res.json()["data"]

    assert data["current_price"] == 1020.0
    assert data["change_pct"] == pytest.approx(2.0)


async def test_get_pick_detail_live_quote_defaults_to_none_on_failure(client: AsyncClient) -> None:
    await pl.insert_pick(_entry("p1", "mid_term", "7203"))
    res = await client.get("/api/picks/p1")
    data = res.json()["data"]
    assert data["current_price"] is None
    assert data["change_pct"] is None


async def test_get_pick_detail_returns_nested_sub_scores_and_rationale(client: AsyncClient) -> None:
    """🆕 ピック詳細ポップアップ用: sub_scores（ネスト）・rationale_struct・source_contributions・
    company_name が揃うこと（`PickDetailResponse` の契約を固定する）."""
    await pl.insert_pick(_entry("p1", "mid_term", "7203"))

    res = await client.get("/api/picks/p1")
    data = res.json()["data"]

    assert data["sub_scores"] == {"technical": 60.0, "trend": 55.0, "fundamental": 52.0, "sentiment": 50.0}
    assert data["rationale_struct"] == {}
    assert data["source_contributions"] == {"technical": {"weight_share": 0.6}}
    assert data["run_id"] == "r1"
    assert data["confidence_raw"] == 70.0
    # company_name は銘柄マスタ（J-Quants 未設定時はフォールバック一覧）から解決できれば入る
    assert "company_name" in data


async def test_get_pick_detail_includes_gemini_shadow_predictions(client: AsyncClient) -> None:
    """🆕 P12: マルチLLM判定 — Gemini 等 challenger の判定が shadow_predictions として同梱される."""
    await pl.insert_pick(_entry("p1", "mid_term", "7203"))
    await insert_shadow_prediction(
        pick_id="p1",
        run_id="r1",
        challenger_version="gemini:gemini-2.5-pro",
        symbol="7203",
        horizon_type="mid_term",
        direction="bullish",
        entry=1005.0,
        stop=980.0,
        target=1060.0,
        confidence_raw=68.0,
        confidence=68.0,
        payload={"reasoning": "Gemini 側の根拠", "risk_factors": ["需給悪化"], "holding_period_days": 6},
    )

    res = await client.get("/api/picks/p1")
    data = res.json()["data"]

    assert len(data["shadow_predictions"]) == 1
    shadow = data["shadow_predictions"][0]
    assert shadow["challenger_version"] == "gemini:gemini-2.5-pro"
    assert shadow["direction"] == "bullish"
    assert shadow["entry"] == 1005.0
    assert shadow["reasoning"] == "Gemini 側の根拠"
    assert shadow["risk_factors"] == ["需給悪化"]
    assert shadow["holding_period_days"] == 6


async def test_get_pick_detail_shadow_predictions_empty_by_default(client: AsyncClient) -> None:
    await pl.insert_pick(_entry("p1", "mid_term", "7203"))
    res = await client.get("/api/picks/p1")
    assert res.json()["data"]["shadow_predictions"] == []


async def test_run_endpoint_invokes_pipeline(client: AsyncClient, monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_run(horizon_type: str) -> PickRunResult:
        return PickRunResult(
            run_id="r9",
            horizon_type=horizon_type,
            issued_at="2026-09-11T08:50:00+09:00",
            status="empty",
            picks=[],
            rejected=[],
            message="候補なし",
        )

    monkeypatch.setattr("backend.routers.picks.run_picks", fake_run)
    res = await client.post("/api/picks/run", json={"horizon_type": "short_term"})
    assert res.status_code == 200
    body = res.json()
    assert body["data"]["status"] == "empty"
    assert body["data"]["horizon_type"] == "short_term"


async def test_run_endpoint_rejects_bad_horizon(client: AsyncClient) -> None:
    res = await client.post("/api/picks/run", json={"horizon_type": "weekly"})
    assert res.status_code == 422
