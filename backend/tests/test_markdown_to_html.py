"""`services/notes/markdown_to_html` の検証（frontend版と同じ変換方針のPython実装）."""

from __future__ import annotations

from backend.services.notes.markdown_to_html import markdown_to_html


def test_converts_headings() -> None:
    assert markdown_to_html("## 中見出し") == "<h2>中見出し</h2>"
    assert markdown_to_html("### 小見出し") == "<h3>小見出し</h3>"


def test_converts_bold() -> None:
    assert markdown_to_html("**強気** な展開です") == "<p><strong>強気</strong> な展開です</p>"


def test_converts_horizontal_rule() -> None:
    assert markdown_to_html("---") == "<hr>"


def test_converts_bullet_list() -> None:
    assert markdown_to_html("- 項目1\n- 項目2") == "<ul><li>項目1</li><li>項目2</li></ul>"


def test_joins_multiple_blocks() -> None:
    html = markdown_to_html("## はじめに\n\n本文です。\n\n---\n\n**強気**")
    assert html == "<h2>はじめに</h2>\n<p>本文です。</p>\n<hr>\n<p><strong>強気</strong></p>"


def test_line_breaks_within_paragraph_become_br() -> None:
    assert markdown_to_html("1行目\n2行目") == "<p>1行目<br>2行目</p>"


def test_escapes_html_for_xss_protection() -> None:
    assert markdown_to_html("<script>alert(1)</script>") == "<p>&lt;script&gt;alert(1)&lt;/script&gt;</p>"
