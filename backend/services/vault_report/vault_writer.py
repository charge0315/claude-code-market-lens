"""レポート・チャートをVaultへ書き込む（🆕 Alpha Forge 初の Vault 書き込み経路）.

`Daily/AlphaForge/<日付>/` 配下に隔離する。Market Lens が書く `Daily/YYYY-MM-DD.md` とは
別パスのため上書き・衝突しない。`daily_note_service.read_daily_frontmatter()` /
`news_digest_service` が読むのは `Daily/*.md`（このサブフォルダの中身は対象外）のため、
AIが自分の過去出力を未来の分析入力として読み込む自己参照ループも起きない
（ユーザー確認済み、CLAUDE.md「Vaultは読み取り専用が原則」の例外運用）。
"""

from __future__ import annotations

from pathlib import Path

from backend.config import settings

_REPORT_MARKER_DIR = "AlphaForge"


def report_dir_for_date(report_date: str) -> Path:
    """`Daily/AlphaForge/<report_date>/` の絶対パスを返す（存在は保証しない）."""
    return settings.resolved_daily_notes_dir / _REPORT_MARKER_DIR / report_date


def write_report(report_date: str, *, html: str, charts: dict[str, str]) -> Path:
    """`report.html` と `charts/<symbol>.svg` 群を書き込み、レポートディレクトリのパスを返す.

    `charts` は {symbol: svg_text} の対応。既存ファイルがあれば上書きする（再生成時に古い
    チャート・本文を残さないため）。
    """
    report_dir = report_dir_for_date(report_date)
    charts_dir = report_dir / "charts"
    charts_dir.mkdir(parents=True, exist_ok=True)

    (report_dir / "report.html").write_text(html, encoding="utf-8")
    for symbol, svg in charts.items():
        (charts_dir / f"{symbol}.svg").write_text(svg, encoding="utf-8")

    return report_dir


def write_pipeline_log(log_date: str, markdown: str) -> Path:
    """`pipeline_log.md` を書き込み、保存先パスを返す（🆕 P30、既存ファイルは上書き）."""
    report_dir = report_dir_for_date(log_date)
    report_dir.mkdir(parents=True, exist_ok=True)
    log_path = report_dir / "pipeline_log.md"
    log_path.write_text(markdown, encoding="utf-8")
    return log_path
