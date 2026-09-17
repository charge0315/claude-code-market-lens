"""note下書きのObsidian(.md)・SingleHTML書き出し（🆕 ユーザー指示: 毎朝Obsidianを確認して
note.comへ手動で貼り付ける運用のための出力）.

`90_Meta/Templates/StockForNote.md`（ユーザー提供テンプレート）のfrontmatterスキーマを踏襲する。
同テンプレートのサマリーテーブル・売買戦略欄には目安買値・損切りライン・目標利確（3値）が
含まれるが、投資助言業への抵触を避けるため出力には一切含めない（ユーザー確認済み、
`note_generator.py` のプロンプト指示で担保）。`Daily/AlphaForge/<日付>/` は
`services/vault_report` と共有するマーカーディレクトリ（Market Lensと衝突しない）。
"""

from __future__ import annotations

from datetime import datetime
from html import escape
from pathlib import Path

import yaml

from backend.models.note import DailyNote
from backend.services.jst_time import JST
from backend.services.ledger import prediction_ledger as pl
from backend.services.notes.markdown_to_html import markdown_to_html
from backend.services.notes.table_image import extract_and_render_tables
from backend.services.vault_report.chart_svg import render_chart_svg
from backend.services.vault_report.price_history import fetch_price_history_before
from backend.services.vault_report.vault_writer import report_dir_for_date

_FIXED_TAGS = [
    "note/stock",
    "ai-pick",
    "moc",
    "market/morning",
    "日本株",
    "投資戦略",
    "デイトレ",
    "スイングトレード",
]


def _extract_summary(body_markdown: str, *, max_len: int = 120) -> str:
    """本文冒頭の段落からサマリーを作る（frontmatterのsummary用、簡易抽出）."""
    for block in body_markdown.split("\n\n"):
        text = block.strip().lstrip("#").strip()
        if text and not text.startswith(("-", "|", "```")):
            return text[:max_len]
    return ""


def build_obsidian_note(note: DailyNote) -> tuple[str, dict[str, bytes]]:
    """`StockForNote.md` のfrontmatterスキーマでObsidianノート全文を組み立てる.

    本文中のMarkdown表はnote.com・Obsidianいずれのリッチペーストでも正しく解釈されない
    （実機確認済み）ため、JPEG画像に変換し `![[.../table_N.jpg]]` 埋め込みへ差し替える
    （ユーザー指示: Obsidianで表示すればそのまま画像として貼り付けられる形にする。
    note.comはSVGアップロードを受け付けないためJPEGを使う、実機確認済み）。
    戻り値は (本文, {ファイル名: JPEGバイト列}) — 画像は呼び出し元が `tables/` へ書き込む。
    """
    embed_dir = f"Daily/AlphaForge/{note.note_date}/tables"
    body_with_tables, table_images = extract_and_render_tables(note.body_markdown, embed_dir=embed_dir)
    now = datetime.now(JST).isoformat(timespec="seconds")
    frontmatter = {
        "title": note.title,
        "date": note.note_date,
        "updated": now,
        "tags": list(_FIXED_TAGS),
        "category": "投資分析・note発信",
        "type": "note-template-moc",
        "author": "AI Market Analyst",
        "status": note.status,
        "target_market": "東証プライム・スタンダード・グロース",
        "summary": _extract_summary(note.body_markdown),
    }
    yaml_block = yaml.dump(frontmatter, allow_unicode=True, sort_keys=False, default_flow_style=False)
    md = f"---\n{yaml_block}---\n\n# {note.title}\n\n{body_with_tables}\n"
    return md, table_images


def build_single_html(note: DailyNote, charts: dict[str, str]) -> str:
    """チャートSVGをすべてインライン埋め込みした自己完結HTML（1ファイル）を組み立てる."""
    body_html = markdown_to_html(note.body_markdown)
    chart_gallery = (
        "".join(f"<figure><figcaption>{escape(symbol)}</figcaption>{svg}</figure>" for symbol, svg in charts.items())
        or "<p>チャートはありません</p>"
    )
    title = escape(note.title)

    return f"""<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="utf-8">
<title>{title}</title>
<style>
body {{ font-family: -apple-system, "Segoe UI", "Hiragino Sans", sans-serif; background: #f5ead8;
       color: #201e1d; max-width: 720px; margin: 0 auto; padding: 24px 16px; line-height: 1.8; }}
h1, h2, h3 {{ color: #201e1d; }}
h2 {{ border-bottom: 2px solid #c67139; padding-bottom: 4px; }}
figure {{ margin: 16px 0; }}
figcaption {{ font-size: 0.85rem; color: #5c584f; margin-bottom: 4px; }}
svg {{ max-width: 100%; height: auto; border-radius: 8px; }}
table {{ border-collapse: collapse; width: 100%; margin: 16px 0; font-size: 0.9rem; }}
th, td {{ border: 1px solid #c9bfa8; padding: 6px 10px; text-align: left; }}
th {{ background: #c67139; color: #fffaf2; }}
tbody tr:nth-child(even) {{ background: #efe0c8; }}
.disclaimer {{ color: #5c584f; font-size: 0.8rem; border-top: 1px solid #c9bfa8; padding-top: 12px; margin-top: 24px; }}
</style>
</head>
<body>
<h1>{title}</h1>
{body_html}
<h2>参考チャート</h2>
{chart_gallery}
</body>
</html>
"""


def write_note_files(
    note: DailyNote, *, obsidian_md: str, single_html: str, table_images: dict[str, bytes] | None = None
) -> Path:
    """`Daily/AlphaForge/<日付>/note.md`・`note_single.html`・（あれば）`tables/*.jpg` を書き込む.

    `tables/` は書き込み前に一旦空にする。再生成のたびに表の数が変わりうるため、そのままだと
    古い回の画像（例: 前回は table_3.jpg まであったが今回は table_2.jpg まで）が消えずに残り、
    note.md からは参照されない孤立ファイルになってしまう。
    """
    note_dir = report_dir_for_date(note.note_date)
    note_dir.mkdir(parents=True, exist_ok=True)
    (note_dir / "note.md").write_text(obsidian_md, encoding="utf-8")
    (note_dir / "note_single.html").write_text(single_html, encoding="utf-8")
    tables_dir = note_dir / "tables"
    if tables_dir.exists():
        for existing in tables_dir.iterdir():
            if existing.is_file():
                existing.unlink()
    if table_images:
        tables_dir.mkdir(parents=True, exist_ok=True)
        for filename, jpeg_bytes in table_images.items():
            (tables_dir / filename).write_bytes(jpeg_bytes)
    return note_dir


async def export_note_files(note: DailyNote) -> Path:
    """本日のnote下書きから Obsidian(.md)・SingleHTML を生成し、Vaultへ書き込む.

    チャートはピック前日までの終値から生成する（`services/vault_report` と同じロジックを再利用、
    未来リーク防止）。`note.source_pick_ids` に対応する銘柄を、同日の公式ピック一覧
    （`prediction_ledger.list_picks`）から引いて symbol/company_name を得る。
    """
    mid_term = await pl.list_picks(horizon_type="mid_term", issued_from=f"{note.note_date}T00:00:00", limit=50)
    short_term = await pl.list_picks(horizon_type="short_term", issued_from=f"{note.note_date}T00:00:00", limit=50)
    source_ids = set(note.source_pick_ids)
    picks = [p for p in (*mid_term, *short_term) if p.pick_id in source_ids]

    charts: dict[str, str] = {}
    for p in picks:
        series = await fetch_price_history_before(p.symbol, note.note_date)
        title = f"{p.symbol}（{p.company_name}）" if p.company_name else p.symbol
        svg = render_chart_svg(title, series)
        if svg is not None:
            charts[p.symbol] = svg

    obsidian_md, table_images = build_obsidian_note(note)
    single_html = build_single_html(note, charts)
    return write_note_files(note, obsidian_md=obsidian_md, single_html=single_html, table_images=table_images)
