"""Vaultアーカイブレポート API（🆕）.

本日のAIピックの根拠・4分析内訳・チャート・市況ニュースをHTMLにまとめ、Obsidian Vault
（`Daily/AlphaForge/<日付>/`）へ保存する。個人用アーカイブのため、note下書きと違い承認フローは
持たない（生成＝即保存）。
"""

from __future__ import annotations

from fastapi import APIRouter

from backend.models.common import ApiResponse
from backend.models.vault_report import VaultReportResult
from backend.services.vault_report.report_service import generate_report_for_date

router = APIRouter(prefix="/api/vault-reports", tags=["vault-reports"])


@router.post("/generate", response_model=ApiResponse[VaultReportResult], summary="Vaultアーカイブレポートを生成")
async def generate(date: str | None = None) -> ApiResponse[VaultReportResult]:
    """指定日（省略時はJST本日）のレポートを生成し、Vaultへ保存する."""
    return ApiResponse.ok(await generate_report_for_date(date))
