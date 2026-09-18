"""日次 PIT スナップショット収集サービスの検証（🆕 P29）."""

from __future__ import annotations

from pathlib import Path

import pytest

from backend.models.stocks import TickerInfo
from backend.services.db import pit_snapshot_db
from backend.services.jst_time import today_jst
from backend.services.learning import pit_snapshot_service as svc
from backend.services.learning.pit_provider import PitFundamentalRecord
from backend.services.scoring.llm_news_sentiment_service import LlmNewsSentimentResult


class _FakeProvider:
    def __init__(self, source_id: str, records: dict[str, PitFundamentalRecord | None]) -> None:
        self.source_id = source_id
        self._records = records
        self.calls: list[str] = []

    async def fetch(self, code: str) -> PitFundamentalRecord | None:
        self.calls.append(code)
        return self._records.get(code)


def _record(code: str, *, source: str = "vault_frontmatter", per_forecast: float | None = 15.0) -> PitFundamentalRecord:
    return PitFundamentalRecord(
        code=code,
        source=source,
        data_as_of="2026-09-17",
        per_forecast=per_forecast,
        pbr=1.2,
        roe=0.1,
        equity_ratio=0.4,
        dividend_yield_forecast=0.02,
        eps_forecast=100.0,
        bps=1000.0,
        market_cap_oku=1000.0,
        shares_outstanding=1_000_000,
        last_earnings_date="2026-08-01",
        last_earnings_type="Q1",
        sector33="輸送用機器",
        sector17=None,
        scale_cat=None,
        market="プライム",
    )


async def test_collect_fundamental_snapshots_writes_and_counts(migrated_db: Path) -> None:
    provider = _FakeProvider("vault_frontmatter", {"7203": _record("7203"), "9999": None})

    stats = await svc.collect_fundamental_snapshots(["7203", "9999"], providers=(provider,))

    assert stats.attempted == 2
    assert stats.collected == 1
    rows = await pit_snapshot_db.list_fundamental_range(codes=["7203"], since="2000-01-01", until="2100-01-01")
    assert len(rows) == 1
    assert rows[0]["per_forecast"] == 15.0


async def test_collect_fundamental_snapshots_falls_through_provider_priority(migrated_db: Path) -> None:
    """先頭プロバイダが `None` を返した銘柄は、次のプロバイダで試される."""
    primary = _FakeProvider("vault_frontmatter", {"7203": None})
    fallback = _FakeProvider("shikiho", {"7203": _record("7203", source="shikiho", per_forecast=20.0)})

    stats = await svc.collect_fundamental_snapshots(["7203"], providers=(primary, fallback))

    assert stats.collected == 1
    assert primary.calls == ["7203"]
    assert fallback.calls == ["7203"]
    rows = await pit_snapshot_db.list_fundamental_range(codes=["7203"], since="2000-01-01", until="2100-01-01")
    assert rows[0]["source"] == "shikiho"
    assert rows[0]["per_forecast"] == 20.0


async def test_collect_fundamental_snapshots_one_failure_does_not_stop_others(
    migrated_db: Path, caplog: pytest.LogCaptureFixture
) -> None:
    class _RaisingProvider:
        source_id = "broken"

        async def fetch(self, code: str) -> PitFundamentalRecord | None:
            if code == "7203":
                raise RuntimeError("boom")
            return _record(code)

    stats = await svc.collect_fundamental_snapshots(["7203", "9984"], providers=(_RaisingProvider(),))

    assert stats.attempted == 2
    assert stats.collected == 1
    rows = await pit_snapshot_db.list_fundamental_range(codes=["9984"], since="2000-01-01", until="2100-01-01")
    assert len(rows) == 1


async def test_collect_sentiment_snapshots_keyword_records_zero_count_too(
    migrated_db: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """ニュース 0 件（中立扱い）も「情報あり」として `news_count=0` の行を残すこと."""

    def fake_get_news_sentiment(code: str, max_items: int = 20) -> dict[str, object]:  # noqa: ARG001
        if code == "7203":
            return {"total": 3, "positive": 2, "negative": 1, "neutral": 0, "average_score": 0.7}
        return {"total": 0, "positive": 0, "negative": 0, "neutral": 0, "average_score": 0.5}

    monkeypatch.setattr(svc, "get_news_sentiment", fake_get_news_sentiment)

    stats = await svc.collect_sentiment_snapshots_keyword(["7203", "9984"])

    assert stats.attempted == 2
    assert stats.collected == 1  # ニュース有りの1銘柄のみ「収集」とカウント
    rows = await pit_snapshot_db.list_sentiment_range(
        codes=["7203", "9984"], since="2000-01-01", until="2100-01-01", source="keyword"
    )
    by_code = {r["code"]: r for r in rows}
    assert by_code["7203"]["news_count"] == 3
    assert by_code["7203"]["keyword_score"] == 0.7
    assert by_code["9984"]["news_count"] == 0
    assert by_code["9984"]["keyword_score"] is None  # 中立の 0.5 をそのまま特徴量化しない


async def test_record_llm_sentiment_snapshot_writes_row(migrated_db: Path) -> None:
    result = LlmNewsSentimentResult(
        ticker="7203",
        sentiment_label="positive",
        sentiment_score=0.5,
        impact_score=40.0,
        confidence=60.0,
        reasoning="SECRET テスト用",
        news_count=4,
        generated_at="2026-09-18T08:50:00+09:00",
    )

    await svc.record_llm_sentiment_snapshot("7203", result)

    rows = await pit_snapshot_db.list_sentiment_range(
        codes=["7203"], since=today_jst(), until=today_jst(), source="llm"
    )
    assert len(rows) == 1
    assert rows[0]["llm_sentiment_label"] == "positive"
    assert rows[0]["news_count"] == 4


async def test_record_llm_sentiment_snapshot_is_fail_soft(migrated_db: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """DB 書き込みが失敗しても例外を外へ伝播させないこと（ピック生成本体を止めないため）."""

    async def _raise(**_kwargs: object) -> None:
        raise RuntimeError("db down")

    monkeypatch.setattr(pit_snapshot_db, "upsert_sentiment_snapshot", _raise)
    result = LlmNewsSentimentResult(
        ticker="7203",
        sentiment_label="positive",
        sentiment_score=0.5,
        impact_score=40.0,
        confidence=60.0,
        reasoning="x",
        news_count=1,
        generated_at="2026-09-18T08:50:00+09:00",
    )

    await svc.record_llm_sentiment_snapshot("7203", result)  # 例外が飛ばないこと自体が検証対象


async def test_resolve_snapshot_codes_universe_uses_ticker_master(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_master() -> list[TickerInfo]:
        return [TickerInfo(code="7203", name="トヨタ"), TickerInfo(code="9984", name="ソフトバンクG")]

    monkeypatch.setattr(svc, "_get_ticker_master", fake_master)

    codes = await svc.resolve_snapshot_codes("universe")
    assert codes == ["7203", "9984"]


async def test_resolve_snapshot_codes_candidates_merges_pools_deduped(monkeypatch: pytest.MonkeyPatch) -> None:
    from backend.services.picks import pipeline

    async def fake_pool(horizon_type: str, limit: int) -> list[str]:  # noqa: ARG001
        return ["7203", "9984"] if horizon_type == "mid_term" else ["9984", "6758"]

    monkeypatch.setattr(pipeline, "_candidate_pool", fake_pool)

    codes = await svc.resolve_snapshot_codes("candidates")
    assert codes == ["7203", "9984", "6758"]


async def test_resolve_snapshot_codes_watchlist_uses_holdings(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_holdings() -> list[dict[str, object]]:
        return [{"symbol": "7203"}, {"symbol": "7203"}, {"symbol": "9984"}]

    monkeypatch.setattr(svc, "list_holdings", fake_holdings)

    codes = await svc.resolve_snapshot_codes("watchlist")
    assert codes == ["7203", "9984"]


async def test_resolve_snapshot_codes_unknown_scope_raises() -> None:
    with pytest.raises(ValueError, match="未知の PIT 収集スコープ"):
        await svc.resolve_snapshot_codes("bogus")
