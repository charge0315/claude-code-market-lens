"""`services/notes/wordpress_export` の検証（WXR組み立て・CDATA安全性・サイズ上限）."""

from __future__ import annotations

import pytest

from backend.models.note import DailyNote
from backend.services.notes import wordpress_export as wxr


def _note(**overrides: object) -> DailyNote:
    defaults: dict[str, object] = {
        "note_id": "n1",
        "note_date": "2026-09-17",
        "title": "2026年9月17日 AI銘柄ピック分析note",
        "body_markdown": "## はじめに\n\n本日の分析結果です。\n\n### 7203\n\n強気の展開です。",
        "status": "draft",
        "source_pick_ids": ["p1"],
        "model_version": "anthropic:claude-sonnet-5",
        "has_price_mention_warning": False,
        "generated_at": "2026-09-17T08:05:00+09:00",
    }
    defaults.update(overrides)
    return DailyNote(**defaults)


def test_build_wxr_xml_has_wxr_1_2_structure() -> None:
    note = _note()

    xml = wxr.build_wxr_xml(note, table_image_filenames=[])

    assert "<wp:wxr_version>1.2</wp:wxr_version>" in xml
    assert '<rss version="2.0"' in xml
    assert note.title in xml


def test_build_wxr_xml_maps_published_status_to_publish() -> None:
    note = _note(status="published")

    xml = wxr.build_wxr_xml(note, table_image_filenames=[])

    assert "<wp:status>publish</wp:status>" in xml


def test_build_wxr_xml_maps_draft_status_to_draft() -> None:
    note = _note(status="approved")

    xml = wxr.build_wxr_xml(note, table_image_filenames=[])

    assert "<wp:status>draft</wp:status>" in xml


def test_build_wxr_xml_includes_attachment_item_per_table_image() -> None:
    note = _note()

    xml = wxr.build_wxr_xml(note, table_image_filenames=["table_1.jpg", "table_2.jpg"])

    assert xml.count("<wp:post_type>attachment</wp:post_type>") == 2
    assert "<wp:attachment_url>tables/table_1.jpg</wp:attachment_url>" in xml
    assert "<wp:attachment_url>tables/table_2.jpg</wp:attachment_url>" in xml
    assert 'src="tables/table_1.jpg"' in xml


def test_build_wxr_xml_escapes_title_against_xss() -> None:
    note = _note(title="<script>alert(1)</script>")

    xml = wxr.build_wxr_xml(note, table_image_filenames=[])

    assert "<script>alert(1)</script>" not in xml
    assert "&lt;script&gt;" in xml


def test_cdata_neutralizes_terminator_sequence() -> None:
    """`markdown_to_html`のエスケープを経由しない呼び出し元向けの直接的な境界検証.

    本文はmarkdown_to_html内のescape()で`>`が`&gt;`化されるため`]]>`は実際には残らないが、
    `_cdata()`自体は他の呼び出し元が生の文字列を渡しても壊れないよう単体でガードする。
    """
    assert wxr._cdata("変な文字列]]>を含む文") == "<![CDATA[変な文字列]]]]><![CDATA[>を含む文]]>"


def test_build_wxr_xml_rejects_output_over_20mb(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(wxr, "_MAX_WXR_SIZE_BYTES", 100)
    note = _note()

    with pytest.raises(ValueError, match="20MB"):
        wxr.build_wxr_xml(note, table_image_filenames=[])
