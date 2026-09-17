"""`services/notes/table_image` の検証（Markdown表のSVG画像化・埋め込み置換）."""

from __future__ import annotations

from backend.services.notes import table_image as ti


def test_render_table_svg_includes_header_and_cell_text() -> None:
    svg = ti.render_table_svg([["銘柄コード", "方向性"], ["7203", "強気"]])

    assert svg is not None
    assert svg.startswith("<svg")
    assert "銘柄コード" in svg
    assert "7203" in svg
    assert "強気" in svg


def test_render_table_svg_returns_none_for_empty_rows() -> None:
    assert ti.render_table_svg([]) is None


def test_render_table_svg_escapes_cell_text_against_xss() -> None:
    svg = ti.render_table_svg([["<script>alert(1)</script>", "b"]])

    assert svg is not None
    assert "<script>alert(1)</script>" not in svg
    assert "&lt;script&gt;" in svg


def test_extract_and_render_tables_replaces_table_block_with_embed() -> None:
    body = (
        "## サマリー\n\n"
        "本日のピックです。\n\n"
        "| 銘柄コード | 方向性 |\n"
        "|---|---|\n"
        "| 7203 | 強気 |\n"
        "| 9984 | 中立 |\n\n"
        "## まとめ\n\n"
        "以上です。"
    )

    new_body, images = ti.extract_and_render_tables(body, embed_dir="Daily/AlphaForge/2026-09-17/tables")

    assert "| 銘柄コード |" not in new_body
    assert "![[Daily/AlphaForge/2026-09-17/tables/table_1.svg]]" in new_body
    assert "本日のピックです。" in new_body
    assert "## まとめ" in new_body
    assert set(images.keys()) == {"table_1.svg"}
    assert "7203" in images["table_1.svg"]


def test_extract_and_render_tables_numbers_multiple_tables_sequentially() -> None:
    body = "| a | b |\n|---|---|\n| 1 | 2 |\n\n" "テキスト\n\n" "| c | d |\n|---|---|\n| 3 | 4 |"

    new_body, images = ti.extract_and_render_tables(body, embed_dir="dir")

    assert "![[dir/table_1.svg]]" in new_body
    assert "![[dir/table_2.svg]]" in new_body
    assert set(images.keys()) == {"table_1.svg", "table_2.svg"}


def test_extract_and_render_tables_leaves_non_table_body_unchanged() -> None:
    body = "本日の相場概況です。\n\n引き続き堅調に推移しました。"

    new_body, images = ti.extract_and_render_tables(body, embed_dir="dir")

    assert new_body == body
    assert images == {}


def test_extract_and_render_tables_ignores_block_without_separator_row() -> None:
    # 区切り行（|---|---|）が無いのでMarkdown表として扱わない。
    body = "| これは表ではない |\n| ただのテキスト行 |"

    new_body, images = ti.extract_and_render_tables(body, embed_dir="dir")

    assert new_body == body
    assert images == {}
