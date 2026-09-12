"""ピック API の検証（envelope・3 値必須・run 経路）."""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from backend.models.pick import LedgerEntry, PickRunResult, SubScores
from backend.services.ledger import prediction_ledger as pl


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


async def test_get_pick_detail_omits_feature_snapshot(client: AsyncClient) -> None:
    await pl.insert_pick(_entry("p1", "mid_term", "7203"))
    res = await client.get("/api/picks/p1")
    body = res.json()
    assert body["success"] is True
    assert "feature_snapshot" not in body["data"]
    assert body["data"]["symbol"] == "7203"

    missing = await client.get("/api/picks/nope")
    assert missing.json()["success"] is False


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
