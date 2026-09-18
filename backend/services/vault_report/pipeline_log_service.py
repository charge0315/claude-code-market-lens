"""日次パイプラインログのオーケストレーション（🆕 P30）.

`pipeline_log_generator`（Markdown組み立て+件数集計）・`vault_writer`（ファイル書き込み）を束ね、
指定日のパイプライン実行結果（候補プール〜モデル入れ替え）から日次ログを生成し、Vaultへ保存する。
`report_service.generate_report_for_date` と同じ構成。
"""

from __future__ import annotations

from backend.models.vault_report import PipelineLogResult
from backend.services.jst_time import today_jst
from backend.services.vault_report.pipeline_log_generator import build_pipeline_log_markdown
from backend.services.vault_report.vault_writer import write_pipeline_log


async def generate_pipeline_log_for_date(log_date: str | None = None) -> PipelineLogResult:
    """指定日（既定はJST本日）の日次パイプラインログを生成し、Vaultへ保存する."""
    log_date = log_date or today_jst()

    markdown, counts = await build_pipeline_log_markdown(log_date)
    log_path = write_pipeline_log(log_date, markdown)

    return PipelineLogResult(log_date=log_date, log_path=str(log_path), **counts)
