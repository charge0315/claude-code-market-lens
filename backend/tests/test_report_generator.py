"""`services/vault_report/report_generator` の検証（3値を含めないこと、XSS対策、ニュース欄）."""

from __future__ import annotations

import re

import pytest

from backend.services.picks.pick_analysis import PickAnalysis
from backend.services.vault.news_digest_service import DailyNoteDigest
from backend.services.vault_report import report_generator as rg


def make_pick_analysis(
    *, symbol: str, company_name: str | None = "テスト株式会社", **overrides: object
) -> PickAnalysis:
    defaults: dict[str, object] = {
        "symbol": symbol,
        "company_name": company_name,
        "direction": "bullish",
        "composite_score": 61.3,
        "confidence": 58.0,
        "confidence_bucket": "mid",
        "concordance": 1.0,
        "rationale_text": "MACDがゴールデンクロス",
        "reasoning_tags": ["MACD ゴールデンクロス"],
        "sub_scores": {"technical": 62.0, "trend": 20.0, "fundamental": 60.0, "sentiment": 50.0},
        "source_contributions": {"technical": {"weight_share": 0.64, "contribution": 39.5, "score": 62.0}},
        "llm_risk_factors": ["金利上昇リスク"],
        "holding_period_days": 10,
        "pick_id": f"p-{symbol}",
    }
    overrides.pop("entry_would_be", None)  # 3値が存在しないことのテスト用の意図明示（無視する）
    defaults.update(overrides)
    return PickAnalysis(**defaults)  # type: ignore[arg-type]


@pytest.fixture(autouse=True)
def _fake_price_history(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _fake(_symbol: str, _before_date: str) -> list[tuple[str, float]]:
        return [("2026-09-15", 100.0), ("2026-09-16", 110.0)]

    monkeypatch.setattr(rg, "fetch_price_history_before", _fake)


async def test_build_report_html_excludes_entry_stop_target() -> None:
    """個人用アーカイブでも3値（推奨買値/損切値/推奨売値）は一切出力しない（ユーザー確認済み）.

    `PickAnalysis` 自体に entry/stop/target フィールドが無いため構造的に含められない
    （`test_pick_analysis.py` で属性が存在しないことを別途検証済み）。ここでは金額表現
    （円/¥）がHTMLに出てこないことを確認する（末尾の免責文は語として「推奨買値」等の
    ラベルに触れるが、実際の金額は書かない設計のため金額パターンで検証する）。
    """
    pick = make_pick_analysis(symbol="7203")

    html, charts = await rg.build_report_html("2026-09-17", [pick], [], news=())

    assert not re.search(r"[¥￥]\s?\d|\d+\s?円", html)
    assert "7203" in html
    assert "charts" in html
    assert "7203" in charts


async def test_build_report_html_includes_sub_scores_and_source_contributions() -> None:
    pick = make_pick_analysis(symbol="7203")

    html, _charts = await rg.build_report_html("2026-09-17", [pick], [], news=())

    assert "テクニカル" in html
    assert "寄与度64%" in html
    assert "金利上昇リスク" in html


async def test_build_report_html_escapes_untrusted_text_against_xss() -> None:
    pick = make_pick_analysis(symbol="7203", company_name="<img src=x onerror=alert(1)>")

    html, _charts = await rg.build_report_html("2026-09-17", [pick], [], news=())

    assert "<img src=x onerror=alert(1)>" not in html
    assert "&lt;img" in html


async def test_build_report_html_handles_empty_horizon() -> None:
    html, charts = await rg.build_report_html("2026-09-17", [], [], news=())

    assert "本日は該当なし" in html
    assert charts == {}


async def test_build_report_html_includes_news_digest() -> None:
    news = (
        DailyNoteDigest(
            published_on=__import__("datetime").date(2026, 9, 17),
            title="日経平均が反発",
            category="市況",
            fact_checked=True,
            sources=("Reuters",),
            tags=(),
        ),
    )

    html, _charts = await rg.build_report_html("2026-09-17", [], [], news=news)

    assert "日経平均が反発" in html
    assert "Reuters" in html
