"""Vaultアーカイブレポートのオーケストレーション（🆕）.

`report_generator`（HTML組み立て）・`vault_writer`（ファイル書き込み）を束ね、
指定日のAIピック（中長期・短期）から個人用アーカイブレポートを生成する。
"""

from __future__ import annotations

from backend.models.vault_report import VaultReportResult
from backend.services.jst_time import today_jst
from backend.services.ledger import prediction_ledger as pl
from backend.services.picks.pick_analysis import to_pick_analysis
from backend.services.vault.news_digest_service import get_market_news_digest
from backend.services.vault_report.report_generator import build_report_html
from backend.services.vault_report.vault_writer import write_report


async def generate_report_for_date(report_date: str | None = None) -> VaultReportResult:
    """指定日（既定はJST本日）のアーカイブレポートを生成し、Vaultへ保存する."""
    report_date = report_date or today_jst()

    mid_term = await pl.list_picks(horizon_type="mid_term", issued_from=f"{report_date}T00:00:00", limit=50)
    short_term = await pl.list_picks(horizon_type="short_term", issued_from=f"{report_date}T00:00:00", limit=50)
    mid_term_analysis = [await to_pick_analysis(p) for p in mid_term]
    short_term_analysis = [await to_pick_analysis(p) for p in short_term]
    news = await get_market_news_digest()

    html, charts = await build_report_html(report_date, mid_term_analysis, short_term_analysis, news)
    report_dir = write_report(report_date, html=html, charts=charts)

    return VaultReportResult(
        report_date=report_date,
        report_dir=str(report_dir),
        mid_term_count=len(mid_term_analysis),
        short_term_count=len(short_term_analysis),
        chart_count=len(charts),
    )
