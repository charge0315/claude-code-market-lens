"""noteドラフト API（`routers/notes.py`）の検証（envelope・404・状態遷移）."""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from backend.models.pick import LedgerEntry, SubScores
from backend.services.jst_time import today_jst
from backend.services.ledger import prediction_ledger as pl
from backend.services.notes import note_export as ne
from backend.services.notes import note_generator as gen
from backend.tests.conftest import VaultDirs


@pytest.fixture(autouse=True)
def _fake_price_history(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _fake(_symbol: str, _before_date: str) -> list[tuple[str, float]]:
        return [("2026-09-15", 100.0), ("2026-09-16", 110.0)]

    monkeypatch.setattr(ne, "fetch_price_history_before", _fake)


_LONG_BODY = (
    "# 本日の相場概況\n本文です。国内主要指数は堅調に推移し、値がさ株を中心に買いが優勢な展開となりました。"
    "海外市場の流れを引き継ぎ、投資家心理は総じてリスクオンの姿勢が強く、出来高も高水準で推移しています。"
    "個別銘柄では業績上振れ期待の高い企業に資金が集中し、テクニカル指標も強気シグナルを示すものが目立ちました。"
    "引き続き市況の変化には注意しつつ、堅調な展開が続くか見極めていく必要があります。今後の値動きにも注目です。"
)


class _FakeLLM:
    provider_id = "anthropic"
    is_configured = True

    def model_for(self, _feature: str) -> str:
        return "test-model"

    async def propose_daily_note(self, *, prompt: str) -> dict[str, object]:  # noqa: ARG002
        return {"title": "テスト記事", "body_markdown": _LONG_BODY}


@pytest.fixture(autouse=True)
def _fake_llm(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(gen, "resolve_feature_provider", lambda _feature: _FakeLLM())


@pytest_asyncio.fixture
async def client(migrated_db: Path, vault_dirs: VaultDirs) -> AsyncIterator[AsyncClient]:
    # 素材となる本日の公式ピックが無いと note_generator が「該当なし」フォールバックに
    # 入ってしまうため、各テストの前提として1件だけ投入しておく。
    await pl.insert_pick(
        LedgerEntry(
            pick_id="p-router-test",
            run_id="r1",
            issued_at=f"{today_jst()}T08:50:00+09:00",
            horizon_type="mid_term",
            symbol="7203",
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
            feature_snapshot={},
            rationale_struct={},
            rationale_text="反発余地",
            model_version="baseline-2026-09-11",
            source_contributions={},
            created_at=f"{today_jst()}T08:50:01+09:00",
        )
    )

    from backend.main import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac


async def test_get_today_returns_null_when_not_generated(client: AsyncClient) -> None:
    res = await client.get("/api/notes/today")

    assert res.status_code == 200
    body = res.json()
    assert body["success"] is True
    assert body["data"] is None


async def test_generate_then_get_today(client: AsyncClient) -> None:
    gen_res = await client.post("/api/notes/generate")
    assert gen_res.status_code == 200
    generated = gen_res.json()["data"]
    assert generated["title"] == "テスト記事"
    assert generated["status"] == "draft"

    today_res = await client.get("/api/notes/today")
    assert today_res.json()["data"]["note_id"] == generated["note_id"]


async def test_approve_reject_mark_published_flow(client: AsyncClient) -> None:
    generated = (await client.post("/api/notes/generate")).json()["data"]
    note_id = generated["note_id"]

    approved = await client.post(f"/api/notes/{note_id}/approve")
    assert approved.json()["data"]["status"] == "approved"

    published = await client.post(
        f"/api/notes/{note_id}/mark-published", json={"published_url": "https://note.com/example/n/xxx"}
    )
    assert published.json()["data"]["status"] == "published"
    assert published.json()["data"]["published_url"] == "https://note.com/example/n/xxx"


async def test_update_content_edits_body(client: AsyncClient) -> None:
    generated = (await client.post("/api/notes/generate")).json()["data"]
    note_id = generated["note_id"]

    res = await client.patch(f"/api/notes/{note_id}", json={"title": "編集後タイトル", "body_markdown": "編集後本文"})

    assert res.json()["data"]["title"] == "編集後タイトル"
    assert res.json()["data"]["body_markdown"] == "編集後本文"


async def test_approve_missing_note_returns_404(client: AsyncClient) -> None:
    res = await client.post("/api/notes/does-not-exist/approve")

    assert res.status_code == 404


async def test_list_recent_returns_generated_notes(client: AsyncClient) -> None:
    await client.post("/api/notes/generate")

    res = await client.get("/api/notes")

    assert res.status_code == 200
    assert len(res.json()["data"]) == 1


async def test_export_writes_obsidian_and_single_html(client: AsyncClient, vault_dirs: VaultDirs) -> None:
    generated = (await client.post("/api/notes/generate")).json()["data"]
    note_id = generated["note_id"]

    res = await client.post(f"/api/notes/{note_id}/export")

    assert res.status_code == 200
    note_dir_str = res.json()["data"]["note_dir"]
    expected_dir = vault_dirs.daily / "AlphaForge" / today_jst()
    assert Path(note_dir_str) == expected_dir
    assert (expected_dir / "note.md").is_file()
    assert (expected_dir / "note_single.html").is_file()


async def test_export_missing_note_returns_404(client: AsyncClient) -> None:
    res = await client.post("/api/notes/does-not-exist/export")

    assert res.status_code == 404
