"""`services/notes/note_export` の検証（Obsidian/.md・SingleHTML書き出し、3値の非混入）."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from backend.models.note import DailyNote
from backend.models.pick import LedgerEntry, SubScores
from backend.services.ledger import prediction_ledger as pl
from backend.services.notes import note_export as ne
from backend.tests.conftest import VaultDirs


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


def test_build_obsidian_note_has_stockfornote_frontmatter_schema() -> None:
    note = _note()

    md, table_images = ne.build_obsidian_note(note)

    assert md.startswith("---\n")
    frontmatter_text = md.split("---\n")[1]
    frontmatter = yaml.safe_load(frontmatter_text)
    assert frontmatter["title"] == note.title
    assert frontmatter["date"] == "2026-09-17"
    assert frontmatter["category"] == "投資分析・note発信"
    assert frontmatter["type"] == "note-template-moc"
    assert frontmatter["status"] == "draft"
    assert "note/stock" in frontmatter["tags"]
    assert note.body_markdown in md
    assert table_images == {}


def test_build_obsidian_note_replaces_table_with_jpeg_embed() -> None:
    note = _note(body_markdown="解説です。\n\n| 銘柄コード | 方向性 |\n|---|---|\n| 7203 | 強気 |")

    md, table_images = ne.build_obsidian_note(note)

    assert "| 銘柄コード |" not in md
    assert "![[Daily/AlphaForge/2026-09-17/tables/table_1.jpg]]" in md
    assert set(table_images.keys()) == {"table_1.jpg"}
    assert table_images["table_1.jpg"].startswith(b"\xff\xd8\xff")


def test_build_single_html_embeds_charts_inline() -> None:
    note = _note()

    html = ne.build_single_html(note, {"7203": "<svg><circle r='1'/></svg>"})

    assert "<svg><circle r='1'/></svg>" in html
    assert "7203" in html
    assert note.title in html


def test_build_single_html_escapes_title_against_xss() -> None:
    note = _note(title="<script>alert(1)</script>")

    html = ne.build_single_html(note, {})

    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;" in html


def test_write_note_files_saves_to_alphaforge_marker_dir(vault_dirs: VaultDirs) -> None:
    note = _note()

    note_dir = ne.write_note_files(note, obsidian_md="---\nfoo: bar\n---\nbody", single_html="<html>x</html>")

    assert note_dir == vault_dirs.daily / "AlphaForge" / "2026-09-17"
    assert (note_dir / "note.md").read_text(encoding="utf-8") == "---\nfoo: bar\n---\nbody"
    assert (note_dir / "note_single.html").read_text(encoding="utf-8") == "<html>x</html>"
    assert not (note_dir / "tables").exists()


def test_write_note_files_saves_table_images_when_present(vault_dirs: VaultDirs) -> None:
    note = _note()

    note_dir = ne.write_note_files(
        note,
        obsidian_md="body",
        single_html="<html>x</html>",
        table_images={"table_1.jpg": b"\xff\xd8\xff\x00fake"},
    )

    assert (note_dir / "tables" / "table_1.jpg").read_bytes() == b"\xff\xd8\xff\x00fake"


def test_write_note_files_clears_stale_table_images_from_previous_export(vault_dirs: VaultDirs) -> None:
    note = _note()
    ne.write_note_files(
        note,
        obsidian_md="body",
        single_html="<html>x</html>",
        table_images={"table_1.jpg": b"a", "table_2.jpg": b"b"},
    )

    note_dir = ne.write_note_files(
        note,
        obsidian_md="body2",
        single_html="<html>y</html>",
        table_images={"table_1.jpg": b"c"},
    )

    tables_dir = note_dir / "tables"
    assert {p.name for p in tables_dir.iterdir()} == {"table_1.jpg"}
    assert (tables_dir / "table_1.jpg").read_bytes() == b"c"


def _entry(pick_id: str, symbol: str, *, issued_at: str) -> LedgerEntry:
    return LedgerEntry(
        pick_id=pick_id,
        run_id="r1",
        issued_at=issued_at,
        horizon_type="mid_term",
        symbol=symbol,
        direction="bullish",
        entry=1002.0,
        stop=985.0,
        target=1050.0,
        sub_scores=SubScores(technical=62, trend=20, fundamental=60, sentiment=50),
        composite_score=61.3,
        concordance=1.0,
        confidence_raw=58.0,
        confidence=58.0,
        confidence_bucket="mid",
        feature_snapshot={},
        rationale_struct={},
        rationale_text="MACDがゴールデンクロス",
        model_version="baseline-2026-09-11",
        source_contributions={},
        created_at=issued_at,
    )


@pytest.fixture(autouse=True)
def _fake_price_history(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _fake(_symbol: str, _before_date: str) -> list[tuple[str, float]]:
        return [("2026-09-15", 100.0), ("2026-09-16", 110.0)]

    monkeypatch.setattr(ne, "fetch_price_history_before", _fake)


async def test_export_note_files_writes_md_and_html_without_three_values(
    migrated_db: Path, vault_dirs: VaultDirs
) -> None:
    await pl.insert_pick(_entry("p1", "7203", issued_at="2026-09-17T08:50:00+09:00"))
    note = _note(source_pick_ids=["p1"])

    note_dir = await ne.export_note_files(note)

    assert (note_dir / "note.md").is_file()
    assert (note_dir / "note_single.html").is_file()
    md = (note_dir / "note.md").read_text(encoding="utf-8")
    html = (note_dir / "note_single.html").read_text(encoding="utf-8")
    assert "1002" not in md  # entry
    assert "985" not in md  # stop
    assert "1050" not in md  # target
    assert "1002" not in html
    assert "<svg" in html  # チャートが埋め込まれている


async def test_export_note_files_renders_table_as_jpeg_image(migrated_db: Path, vault_dirs: VaultDirs) -> None:
    await pl.insert_pick(_entry("p1", "7203", issued_at="2026-09-17T08:50:00+09:00"))
    note = _note(
        source_pick_ids=["p1"],
        body_markdown="解説です。\n\n| 銘柄コード | 方向性 |\n|---|---|\n| 7203 | 強気 |",
    )

    note_dir = await ne.export_note_files(note)

    md = (note_dir / "note.md").read_text(encoding="utf-8")
    assert "| 銘柄コード |" not in md
    assert "![[Daily/AlphaForge/2026-09-17/tables/table_1.jpg]]" in md
    table_jpeg = (note_dir / "tables" / "table_1.jpg").read_bytes()
    assert table_jpeg.startswith(b"\xff\xd8\xff")
