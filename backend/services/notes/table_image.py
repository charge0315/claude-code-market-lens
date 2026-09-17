"""Markdown表をJPEG画像へ変換し、Obsidian埋め込み記法に差し替える（🆕 ユーザー指示）.

note.com へのHTML貼り付け・Obsidianでのテーブル記法はいずれもGFM形式の表（`| ... |`）を
正しく解釈できず、パイプ文字がそのまま本文に残ってしまう（実機確認済み）。そのためnote下書きの
Obsidian(.md)書き出しでは、本文中の表を検出してJPEG画像として描画し、`![[.../table_N.jpg]]` の
Obsidian埋め込み記法に置き換える。Obsidianで開けば画像として正しく表示され、そのまま
note.comへ画像として貼り付けられる（画面キャプチャという手作業を不要にする）。

当初SVGで実装したが、note.comがSVGファイルの貼り付け/アップロードを受け付けないことが
実機確認で判明したため（ユーザー指示）、Pillowでラスタライズした JPEG に切り替えた。
日本語描画にはWindowsシステムフォント（Noto Sans JP優先、無ければMeiryo/游ゴシック）を使う
（CLAUDE.md: 開発環境はWindows前提）。
"""

from __future__ import annotations

import io
import re
from functools import lru_cache
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

_ROW_HEIGHT = 34
_HEADER_HEIGHT = 40
_CELL_PAD_X = 12
_FONT_SIZE = 16
_MIN_COL_WIDTH = 70
_MAX_COL_WIDTH = 260
_JPEG_QUALITY = 92

_BG_RGB = (245, 234, 216)  # #f5ead8
_HEADER_BG_RGB = (198, 113, 57)  # #c67139
_HEADER_TEXT_RGB = (255, 250, 242)  # #fffaf2
_TEXT_RGB = (32, 30, 29)  # #201e1d
_BORDER_RGB = (201, 191, 168)  # #c9bfa8
_STRIPE_RGB = (239, 224, 200)  # #efe0c8

# 優先順（Noto Sans JP → Meiryo → 游ゴシック → MSゴシック）。存在しない環境ではPillowの
# 組み込みビットマップフォント（CJK非対応）へ最終フォールバックする。
_FONT_CANDIDATES = [
    Path(r"C:\Windows\Fonts\NotoSansJP-VF.ttf"),
    Path(r"C:\Windows\Fonts\meiryo.ttc"),
    Path(r"C:\Windows\Fonts\YuGothR.ttc"),
    Path(r"C:\Windows\Fonts\msgothic.ttc"),
]
_FONT_BOLD_CANDIDATES = [
    Path(r"C:\Windows\Fonts\NotoSansJP-VF.ttf"),
    Path(r"C:\Windows\Fonts\meiryob.ttc"),
    Path(r"C:\Windows\Fonts\YuGothB.ttc"),
    Path(r"C:\Windows\Fonts\msgothic.ttc"),
]

_TABLE_ROW_RE = re.compile(r"^\|.*\|$")
_SEPARATOR_CELL_RE = re.compile(r"^:?-{1,}:?$")


@lru_cache(maxsize=2)
def _font(*, bold: bool) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    for path in _FONT_BOLD_CANDIDATES if bold else _FONT_CANDIDATES:
        if path.exists():
            try:
                return ImageFont.truetype(str(path), _FONT_SIZE)
            except OSError:
                continue
    return ImageFont.load_default()


def _is_separator_row(line: str) -> bool:
    parts = [p.strip() for p in line.strip().strip("|").split("|")]
    return bool(parts) and all(_SEPARATOR_CELL_RE.match(p) for p in parts)


def is_table_block(lines: list[str]) -> bool:
    return len(lines) >= 2 and all(_TABLE_ROW_RE.match(line) for line in lines) and _is_separator_row(lines[1])


def parse_table_block(block: str) -> list[list[str]]:
    lines = [line.strip() for line in block.strip().split("\n") if line.strip()]
    data_lines = [lines[0], *lines[2:]]
    return [[cell.strip() for cell in line.strip().strip("|").split("|")] for line in data_lines]


def _fit_text(text: str, max_width: int, font: ImageFont.FreeTypeFont | ImageFont.ImageFont) -> str:
    if font.getlength(text) <= max_width:
        return text
    truncated = text
    while truncated and font.getlength(f"{truncated}…") > max_width:
        truncated = truncated[:-1]
    return f"{truncated}…" if truncated else "…"


def render_table_jpeg(rows: list[list[str]]) -> bytes | None:
    """表データ（1行目=ヘッダ）からJPEGテーブル画像のバイト列を返す（データが無ければNone）."""
    if not rows:
        return None
    col_count = max(len(r) for r in rows)
    normalized = [row + [""] * (col_count - len(row)) for row in rows]
    regular, bold = _font(bold=False), _font(bold=True)

    col_widths = []
    for i in range(col_count):
        header_w = bold.getlength(normalized[0][i])
        body_w = max((regular.getlength(row[i]) for row in normalized[1:]), default=0.0)
        px = _CELL_PAD_X * 2 + int(max(header_w, body_w))
        col_widths.append(max(_MIN_COL_WIDTH, min(_MAX_COL_WIDTH, px)))
    total_width = sum(col_widths)
    total_height = _HEADER_HEIGHT + _ROW_HEIGHT * (len(normalized) - 1)

    image = Image.new("RGB", (total_width, total_height), _BG_RGB)
    draw = ImageDraw.Draw(image)

    y = 0
    for r_idx, row in enumerate(normalized):
        is_header = r_idx == 0
        row_h = _HEADER_HEIGHT if is_header else _ROW_HEIGHT
        row_bg = _HEADER_BG_RGB if is_header else (_STRIPE_RGB if r_idx % 2 == 0 else _BG_RGB)
        text_color = _HEADER_TEXT_RGB if is_header else _TEXT_RGB
        font = bold if is_header else regular
        draw.rectangle([0, y, total_width, y + row_h], fill=row_bg)
        x = 0
        for c_idx, cell in enumerate(row):
            w = col_widths[c_idx]
            label = _fit_text(cell, w - _CELL_PAD_X * 2, font)
            draw.text((x + _CELL_PAD_X, y + row_h / 2), label, font=font, fill=text_color, anchor="lm")
            x += w
        y += row_h

    y = 0
    for r_idx in range(len(normalized) + 1):
        draw.line([(0, y), (total_width, y)], fill=_BORDER_RGB, width=1)
        if r_idx < len(normalized):
            y += _HEADER_HEIGHT if r_idx == 0 else _ROW_HEIGHT
    x = 0
    for w in [*col_widths, 0]:
        draw.line([(x, 0), (x, total_height)], fill=_BORDER_RGB, width=1)
        x += w

    buffer = io.BytesIO()
    image.save(buffer, format="JPEG", quality=_JPEG_QUALITY)
    return buffer.getvalue()


def extract_and_render_tables(body_markdown: str, *, embed_dir: str) -> tuple[str, dict[str, bytes]]:
    """本文中のMarkdown表を検出し、`![[embed_dir/table_N.jpg]]`埋め込みへ置換する.

    戻り値は (置換後の本文, {ファイル名: JPEGバイト列})。表が無ければ元の本文をそのまま返す。
    `embed_dir` はObsidianのVaultルートからの相対パス（例: `Daily/AlphaForge/2026-09-17/tables`）。
    ファイル名は日付ごとのフォルダ内で完結するがVault全体では同名になりうるため、Obsidianの
    埋め込みリンクが誤って別日のノートを指さないよう、常にこのフルパスで埋め込む。
    """
    blocks = body_markdown.split("\n\n")
    images: dict[str, bytes] = {}
    table_no = 0
    new_blocks: list[str] = []
    for block in blocks:
        lines = [line.strip() for line in block.strip().split("\n") if line.strip()]
        if is_table_block(lines):
            jpeg = render_table_jpeg(parse_table_block(block))
            if jpeg is not None:
                table_no += 1
                filename = f"table_{table_no}.jpg"
                images[filename] = jpeg
                new_blocks.append(f"![[{embed_dir}/{filename}]]")
                continue
        new_blocks.append(block)
    return "\n\n".join(new_blocks), images
