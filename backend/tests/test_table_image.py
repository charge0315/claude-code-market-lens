"""`services/notes/table_image` の検証（Markdown表のJPEG画像化・埋め込み置換）."""

from __future__ import annotations

import io

from PIL import Image

from backend.services.notes import table_image as ti

_JPEG_MAGIC = b"\xff\xd8\xff"


def _dimensions(jpeg_bytes: bytes) -> tuple[int, int]:
    with Image.open(io.BytesIO(jpeg_bytes)) as img:
        return img.size


def test_render_table_jpeg_returns_valid_jpeg_bytes() -> None:
    jpeg_bytes = ti.render_table_jpeg([["銘柄コード", "方向性"], ["7203", "強気"]])

    assert jpeg_bytes is not None
    assert jpeg_bytes.startswith(_JPEG_MAGIC)
    width, height = _dimensions(jpeg_bytes)
    assert width > 0
    assert height > 0


def test_render_table_jpeg_returns_none_for_empty_rows() -> None:
    assert ti.render_table_jpeg([]) is None


def test_render_table_jpeg_does_not_raise_on_html_like_cell_text() -> None:
    # PillowはHTMLとして解釈しないため、エスケープ不要でそのまま描画できる（例外にならない）。
    jpeg_bytes = ti.render_table_jpeg([["<script>alert(1)</script>", "b"]])

    assert jpeg_bytes is not None
    assert jpeg_bytes.startswith(_JPEG_MAGIC)


def test_render_table_jpeg_wider_table_produces_wider_image() -> None:
    narrow = ti.render_table_jpeg([["a", "b"], ["1", "2"]])
    wide = ti.render_table_jpeg(
        [["銘柄コード", "銘柄名", "方向性", "合成スコア"], ["7203", "トヨタ自動車", "強気", "61.3"]]
    )

    assert narrow is not None
    assert wide is not None
    assert _dimensions(wide)[0] > _dimensions(narrow)[0]


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
    assert "![[Daily/AlphaForge/2026-09-17/tables/table_1.jpg]]" in new_body
    assert "本日のピックです。" in new_body
    assert "## まとめ" in new_body
    assert set(images.keys()) == {"table_1.jpg"}
    assert images["table_1.jpg"].startswith(_JPEG_MAGIC)


def test_extract_and_render_tables_numbers_multiple_tables_sequentially() -> None:
    body = "| a | b |\n|---|---|\n| 1 | 2 |\n\n" "テキスト\n\n" "| c | d |\n|---|---|\n| 3 | 4 |"

    new_body, images = ti.extract_and_render_tables(body, embed_dir="dir")

    assert "![[dir/table_1.jpg]]" in new_body
    assert "![[dir/table_2.jpg]]" in new_body
    assert set(images.keys()) == {"table_1.jpg", "table_2.jpg"}


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
