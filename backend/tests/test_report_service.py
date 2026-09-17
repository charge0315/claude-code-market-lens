"""`services/vault_report/report_service.generate_report_for_date` の検証（end-to-end）."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from backend.models.pick import LedgerEntry, SubScores
from backend.services.ledger import prediction_ledger as pl
from backend.services.vault_report import report_generator as rg
from backend.services.vault_report.report_service import generate_report_for_date
from backend.tests.conftest import VaultDirs


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
        sub_scores=SubScores(technical=62, trend=20, fundamental=60, sentiment=50),
        composite_score=61.3,
        concordance=1.0,
        confidence_raw=58.0,
        confidence=58.0,
        confidence_bucket="mid",
        feature_snapshot={},
        rationale_struct={"llm_risk_factors": ["金利上昇リスク"], "holding_period_days": 10},
        rationale_text="MACDがゴールデンクロス",
        model_version="baseline-2026-09-11",
        source_contributions={},
        created_at=issued_at,
    )


@pytest.fixture(autouse=True)
def _fake_price_history(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _fake(_symbol: str, _before_date: str) -> list[tuple[str, float]]:
        return [("2026-09-15", 100.0), ("2026-09-16", 110.0)]

    monkeypatch.setattr(rg, "fetch_price_history_before", _fake)


async def test_generate_report_for_date_writes_html_and_charts_to_vault(
    migrated_db: Path, vault_dirs: VaultDirs
) -> None:
    await pl.insert_pick(_entry("p-mid", "mid_term", "7203", issued_at="2026-09-17T08:50:00+09:00"))
    await pl.insert_pick(_entry("p-short", "short_term", "9984", issued_at="2026-09-17T08:52:00+09:00"))

    result = await generate_report_for_date("2026-09-17")

    assert result.mid_term_count == 1
    assert result.short_term_count == 1
    assert result.chart_count == 2

    report_dir = vault_dirs.daily / "AlphaForge" / "2026-09-17"
    assert (report_dir / "report.html").is_file()
    assert (report_dir / "charts" / "7203.svg").is_file()
    assert (report_dir / "charts" / "9984.svg").is_file()

    html = (report_dir / "report.html").read_text(encoding="utf-8")
    assert "7203" in html
    assert "9984" in html
    assert not re.search(r"[¥￥]\s?\d|\d+\s?円", html)


async def test_generate_report_for_date_defaults_to_today(migrated_db: Path, vault_dirs: VaultDirs) -> None:
    from backend.services.jst_time import today_jst

    result = await generate_report_for_date()

    assert result.report_date == today_jst()
    assert result.mid_term_count == 0
    assert result.short_term_count == 0
