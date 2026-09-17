"""Markdown表をSVG画像へ変換し、Obsidian埋め込み記法に差し替える（🆕 ユーザー指示）.

note.com へのHTML貼り付け・Obsidianでのテーブル記法はいずれもGFM形式の表（`| ... |`）を
正しく解釈できず、パイプ文字がそのまま本文に残ってしまう（実機確認済み）。そのためnote下書きの
Obsidian(.md)書き出しでは、本文中の表を検出してSVG画像として描画し、`![[.../table_N.svg]]` の
Obsidian埋め込み記法に置き換える。Obsidianで開けば画像として正しく表示され、そのまま
note.comへ画像として貼り付けられる（画面キャプチャという手作業を不要にする）。

`vault_report/chart_svg.py` と同じ配色・SVG直接生成方針（matplotlib等の重い依存を避ける、YAGNI）。
"""

from __future__ import annotations

import re
from html import escape

_ROW_HEIGHT = 30
_HEADER_HEIGHT = 34
_CELL_PAD_X = 10
_FONT_SIZE = 13
_MIN_COL_WIDTH = 60
_MAX_COL_WIDTH = 220
_PER_CHAR_PX = 7  # 半角文字1つあたりの概算幅（_FONT_SIZE基準、全角はこの2倍として扱う）

_BG_HEX = "#f5ead8"
_HEADER_BG_HEX = "#c67139"
_HEADER_TEXT_HEX = "#fffaf2"
_TEXT_HEX = "#201e1d"
_BORDER_HEX = "#c9bfa8"
_STRIPE_HEX = "#efe0c8"

_TABLE_ROW_RE = re.compile(r"^\|.*\|$")
_SEPARATOR_CELL_RE = re.compile(r"^:?-{1,}:?$")


def _display_width(text: str) -> int:
    """CJK・全角文字を2、それ以外を1として概算表示幅を返す（列幅計算用）."""
    width = 0
    for ch in text:
        code = ord(ch)
        is_wide = (
            0x1100 <= code <= 0x115F
            or 0x2E80 <= code <= 0xA4CF
            or 0xAC00 <= code <= 0xD7A3
            or 0xF900 <= code <= 0xFAFF
            or 0xFF00 <= code <= 0xFF60
            or 0xFFE0 <= code <= 0xFFE6
        )
        width += 2 if is_wide else 1
    return width


def _is_separator_row(line: str) -> bool:
    parts = [p.strip() for p in line.strip().strip("|").split("|")]
    return bool(parts) and all(_SEPARATOR_CELL_RE.match(p) for p in parts)


def _is_table_block(lines: list[str]) -> bool:
    return len(lines) >= 2 and all(_TABLE_ROW_RE.match(line) for line in lines) and _is_separator_row(lines[1])


def _parse_table_block(block: str) -> list[list[str]]:
    lines = [line.strip() for line in block.strip().split("\n") if line.strip()]
    data_lines = [lines[0], *lines[2:]]
    return [[cell.strip() for cell in line.strip().strip("|").split("|")] for line in data_lines]


def _col_width(cells: list[str]) -> int:
    max_chars = max((_display_width(c) for c in cells), default=0)
    px = _CELL_PAD_X * 2 + max_chars * _PER_CHAR_PX
    return max(_MIN_COL_WIDTH, min(_MAX_COL_WIDTH, px))


def _fit_text(text: str, col_width: int) -> str:
    max_units = max(1, (col_width - _CELL_PAD_X * 2) // _PER_CHAR_PX)
    if _display_width(text) <= max_units:
        return text
    truncated = ""
    width = 0
    for ch in text:
        unit = _display_width(ch)
        if width + unit > max_units - 1:
            break
        truncated += ch
        width += unit
    return f"{truncated}…"


def render_table_svg(rows: list[list[str]]) -> str | None:
    """表データ（1行目=ヘッダ）からSVGテーブル画像を返す（データが無ければNone）."""
    if not rows:
        return None
    col_count = max(len(r) for r in rows)
    normalized = [row + [""] * (col_count - len(row)) for row in rows]
    col_widths = [_col_width([row[i] for row in normalized]) for i in range(col_count)]
    total_width = sum(col_widths)
    total_height = _HEADER_HEIGHT + _ROW_HEIGHT * (len(normalized) - 1)

    parts = [
        f'<svg width="{total_width}" height="{total_height}" viewBox="0 0 {total_width} {total_height}" '
        f'xmlns="http://www.w3.org/2000/svg" font-family="sans-serif">',
        f'<rect x="0" y="0" width="{total_width}" height="{total_height}" fill="{_BG_HEX}" />',
    ]

    y = 0.0
    for r_idx, row in enumerate(normalized):
        is_header = r_idx == 0
        row_h = _HEADER_HEIGHT if is_header else _ROW_HEIGHT
        row_bg = _HEADER_BG_HEX if is_header else (_STRIPE_HEX if r_idx % 2 == 0 else _BG_HEX)
        text_color = _HEADER_TEXT_HEX if is_header else _TEXT_HEX
        parts.append(f'<rect x="0" y="{y:.1f}" width="{total_width}" height="{row_h}" fill="{row_bg}" />')
        x = 0
        for c_idx, cell in enumerate(row):
            w = col_widths[c_idx]
            label = escape(_fit_text(cell, w))
            weight = ' font-weight="bold"' if is_header else ""
            text_y = y + row_h / 2 + _FONT_SIZE * 0.35
            parts.append(
                f'<text x="{x + _CELL_PAD_X}" y="{text_y:.1f}" font-size="{_FONT_SIZE}" '
                f'fill="{text_color}"{weight}>{label}</text>'
            )
            x += w
        y += row_h

    y = 0.0
    for r_idx in range(len(normalized) + 1):
        parts.append(
            f'<line x1="0" y1="{y:.1f}" x2="{total_width}" y2="{y:.1f}" stroke="{_BORDER_HEX}" stroke-width="1" />'
        )
        if r_idx < len(normalized):
            y += _HEADER_HEIGHT if r_idx == 0 else _ROW_HEIGHT
    x = 0
    for w in [*col_widths, 0]:
        parts.append(f'<line x1="{x}" y1="0" x2="{x}" y2="{total_height}" stroke="{_BORDER_HEX}" stroke-width="1" />')
        x += w

    parts.append("</svg>")
    return "".join(parts)


def extract_and_render_tables(body_markdown: str, *, embed_dir: str) -> tuple[str, dict[str, str]]:
    """本文中のMarkdown表を検出し、`![[embed_dir/table_N.svg]]`埋め込みへ置換する.

    戻り値は (置換後の本文, {ファイル名: SVG文字列})。表が無ければ元の本文をそのまま返す。
    `embed_dir` はObsidianのVaultルートからの相対パス（例: `Daily/AlphaForge/2026-09-17/tables`）。
    ファイル名は日付ごとのフォルダ内で完結するがVault全体では同名になりうるため、Obsidianの
    埋め込みリンクが誤って別日のノートを指さないよう、常にこのフルパスで埋め込む。
    """
    blocks = body_markdown.split("\n\n")
    images: dict[str, str] = {}
    table_no = 0
    new_blocks: list[str] = []
    for block in blocks:
        lines = [line.strip() for line in block.strip().split("\n") if line.strip()]
        if _is_table_block(lines):
            svg = render_table_svg(_parse_table_block(block))
            if svg is not None:
                table_no += 1
                filename = f"table_{table_no}.svg"
                images[filename] = svg
                new_blocks.append(f"![[{embed_dir}/{filename}]]")
                continue
        new_blocks.append(block)
    return "\n\n".join(new_blocks), images
