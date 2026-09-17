"""`services/notes/note_service` の検証（1日1件・再生成・承認フロー）."""

from __future__ import annotations

from pathlib import Path

import pytest

from backend.models.pick import LedgerEntry, SubScores
from backend.services.ledger import prediction_ledger as pl
from backend.services.notes import note_generator as gen
from backend.services.notes import note_service as svc

_LONG_BODY = (
    "# 本日の相場概況\n本文です。国内主要指数は堅調に推移し、値がさ株を中心に買いが優勢な展開となりました。"
    "海外市場の流れを引き継ぎ、投資家心理は総じてリスクオンの姿勢が強く、出来高も高水準で推移しています。"
    "個別銘柄では業績上振れ期待の高い企業に資金が集中し、テクニカル指標も強気シグナルを示すものが目立ちました。"
    "引き続き市況の変化には注意しつつ、堅調な展開が続くか見極めていく必要があります。今後の値動きにも注目です。"
)


class _FakeLLM:
    provider_id = "anthropic"
    is_configured = True

    def __init__(self, title: str, body: str = _LONG_BODY) -> None:
        self._title = title
        self._body = body

    def model_for(self, _feature: str) -> str:
        return "test-model"

    async def propose_daily_note(self, *, prompt: str) -> dict[str, object]:  # noqa: ARG002
        return {"title": self._title, "body_markdown": self._body}


def _entry(pick_id: str, horizon: str, symbol: str, *, issued_at: str) -> LedgerEntry:
    return LedgerEntry(
        pick_id=pick_id,
        run_id="r1",
        issued_at=issued_at,
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
        feature_snapshot={},
        rationale_struct={},
        rationale_text="反発余地",
        model_version="baseline-2026-09-11",
        source_contributions={},
        created_at=issued_at,
    )


async def test_generate_today_reuses_existing_without_force(migrated_db: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from backend.services.jst_time import today_jst

    today = today_jst()
    await pl.insert_pick(_entry("p1", "mid_term", "7203", issued_at=f"{today}T08:50:00+09:00"))

    monkeypatch.setattr(gen, "resolve_feature_provider", lambda _f: _FakeLLM("1回目"))
    first = await svc.generate_today()

    # 2回目は force=False のため LLM を呼ばないはず（呼ばれたら例外で気付く）。
    class _Boom:
        is_configured = True

        async def propose_daily_note(self, *, prompt: str) -> dict[str, object]:  # noqa: ARG002
            raise AssertionError("LLM should not be called")

    monkeypatch.setattr(gen, "resolve_feature_provider", lambda _f: _Boom())
    second = await svc.generate_today()

    assert first.title == second.title == "1回目"
    assert first.note_id == second.note_id


async def test_generate_today_includes_prior_day_outcome_review(
    migrated_db: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """前日決着済みピック（pick_outcomes）の実測値が、note生成プロンプトへ渡ることを検証する（回帰）."""
    from datetime import datetime, timedelta

    from backend.services.db import pick_outcome_db
    from backend.services.jst_time import today_jst

    today = today_jst()
    yesterday = (datetime.fromisoformat(today) - timedelta(days=1)).strftime("%Y-%m-%d")
    await pl.insert_pick(_entry("p-prev", "short_term", "7203", issued_at=f"{yesterday}T08:50:00+09:00"))
    await pick_outcome_db.upsert_outcome(
        pick_id="p-prev",
        horizon_days=1,
        resolved_at=f"{today}T09:05:00+09:00",
        realized_return=0.021,
        win=True,
        hit_stop=False,
        hit_target=True,
        first_hit="target",
        mfe=0.03,
        mae=-0.005,
        benchmark_return=0.006,
        excess_return=0.015,
        confidence_bucket="high",
        direction="bullish",
    )
    await pl.insert_pick(_entry("p-today", "mid_term", "9984", issued_at=f"{today}T08:50:00+09:00"))

    captured: dict[str, str] = {}

    class _CapturingLLM(_FakeLLM):
        async def propose_daily_note(self, *, prompt: str) -> dict[str, object]:
            captured["prompt"] = prompt
            return await super().propose_daily_note(prompt=prompt)

    monkeypatch.setattr(gen, "resolve_feature_provider", lambda _f: _CapturingLLM("t"))

    await svc.generate_today()

    assert "7203" in captured["prompt"]
    assert "実現リターン=2.10%" in captured["prompt"]
    assert "判定=的中" in captured["prompt"]


async def test_generate_today_source_pick_ids_track_todays_official_picks(
    migrated_db: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from backend.services.jst_time import today_jst

    today = today_jst()
    await pl.insert_pick(_entry("p-mid", "mid_term", "7203", issued_at=f"{today}T08:50:00+09:00"))
    await pl.insert_pick(_entry("p-short", "short_term", "9984", issued_at=f"{today}T08:52:00+09:00"))
    monkeypatch.setattr(gen, "resolve_feature_provider", lambda _f: _FakeLLM("t"))

    note = await svc.generate_today()

    assert set(note.source_pick_ids) == {"p-mid", "p-short"}


async def test_regenerate_uses_original_note_date_not_today(migrated_db: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """過去日のドラフトを再生成しても、当日分を上書きしてしまわないこと（回帰）."""
    from backend.services.db import note_db

    old_row = await note_db.upsert_note(
        note_date="2026-09-10",
        title="旧日付",
        body_markdown="本文",
        source_pick_ids=["p1"],
        model_version="anthropic:test",
        has_price_mention_warning=False,
    )
    await pl.insert_pick(_entry("p1", "mid_term", "7203", issued_at="2026-09-10T08:50:00+09:00"))

    monkeypatch.setattr(gen, "resolve_feature_provider", lambda _f: _FakeLLM("旧日付・再生成後"))
    regenerated = await svc.regenerate(str(old_row["note_id"]))

    assert regenerated is not None
    assert regenerated.note_date == "2026-09-10"
    assert regenerated.title == "旧日付・再生成後"
    # 当日分の draft は作られていない。
    assert await svc.get_today() is None


async def test_approve_then_mark_published_flow(migrated_db: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(gen, "resolve_feature_provider", lambda _f: _FakeLLM("t"))
    note = await svc.generate_today()

    approved = await svc.approve(note.note_id)
    assert approved is not None
    assert approved.status == "approved"
    assert approved.approved_at is not None

    published = await svc.mark_published(note.note_id, published_url="https://note.com/example/n/abc")
    assert published is not None
    assert published.status == "published"
    assert published.published_url == "https://note.com/example/n/abc"


async def test_reject_sets_status(migrated_db: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(gen, "resolve_feature_provider", lambda _f: _FakeLLM("t"))
    note = await svc.generate_today()

    rejected = await svc.reject(note.note_id)

    assert rejected is not None
    assert rejected.status == "rejected"


async def test_update_content_returns_none_for_missing_note(migrated_db: Path) -> None:
    result = await svc.update_content("missing-id", title="x", body_markdown="y")

    assert result is None


async def test_get_today_returns_none_when_not_generated_yet(migrated_db: Path) -> None:
    assert await svc.get_today() is None
