"""限定的な Markdown → HTML 変換（🆕 note下書きのSingleHTML書き出し用）.

`frontend/src/lib/markdownToHtml.ts`（note.com貼り付け用のクリップボードコピーで使用）と
同じ変換方針のPython版。note下書きは見出し(#/##/###)・太字(**)・区切り線(---)・箇条書き(-)・
段落のみを使う想定のため、フル仕様のMarkdownパーサーは導入しない（YAGNI）。
"""

from __future__ import annotations

import re
from html import escape

_BOLD_RE = re.compile(r"\*\*(.+?)\*\*")
_ITALIC_RE = re.compile(r"(?<!\*)\*([^*]+?)\*(?!\*)")
_HEADING_RE = re.compile(r"^(#{1,3})\s+(.+)$")
_HR_RE = re.compile(r"^-{3,}$")
_BULLET_RE = re.compile(r"^[-*]\s+")


def _inline_to_html(text: str) -> str:
    escaped = escape(text)
    bolded = _BOLD_RE.sub(r"<strong>\1</strong>", escaped)
    return _ITALIC_RE.sub(r"<em>\1</em>", bolded)


def _block_to_html(block: str) -> str:
    trimmed = block.strip()

    if _HR_RE.match(trimmed):
        return "<hr>"

    heading_match = _HEADING_RE.match(trimmed)
    if heading_match:
        level = len(heading_match.group(1))
        return f"<h{level}>{_inline_to_html(heading_match.group(2))}</h{level}>"

    lines = [line.strip() for line in trimmed.split("\n") if line.strip()]
    if lines and all(_BULLET_RE.match(line) for line in lines):
        items = "".join(f"<li>{_inline_to_html(_BULLET_RE.sub('', line))}</li>" for line in lines)
        return f"<ul>{items}</ul>"

    return f"<p>{'<br>'.join(_inline_to_html(line) for line in lines)}</p>"


def markdown_to_html(markdown: str) -> str:
    blocks = [b.strip() for b in re.split(r"\n{2,}", markdown) if b.strip()]
    return "\n".join(_block_to_html(b) for b in blocks)
