"""PIT ファンダメンタル・プロバイダ抽象の検証（🆕 P29）."""

from __future__ import annotations

from backend.services.learning import pit_provider
from backend.services.vault import brand_notes_service
from backend.tests.conftest import VaultDirs


async def test_vault_frontmatter_provider_maps_brand_note_fields(vault_dirs: VaultDirs) -> None:
    (vault_dirs.tickers / "7203_トヨタ自動車.md").write_text(
        '---\ncode: "7203"\nname: "トヨタ自動車"\nsector33: "輸送用機器"\n'
        'per_forecast: 15.2\npbr: 1.3\nroe: 12.0\ndata_as_of: "2026-09-17"\n---\n\n本文は読まない\n',
        encoding="utf-8",
    )
    brand_notes_service.clear_cache()

    provider = pit_provider.VaultFrontmatterProvider()
    record = await provider.fetch("7203")

    assert record is not None
    assert record.code == "7203"
    assert record.source == "vault_frontmatter"
    assert record.per_forecast == 15.2
    assert record.pbr == 1.3
    assert record.roe == 12.0
    assert record.data_as_of == "2026-09-17"
    assert record.sector33 == "輸送用機器"


async def test_vault_frontmatter_provider_falls_back_to_close_date_when_data_as_of_missing(
    vault_dirs: VaultDirs,
) -> None:
    (vault_dirs.tickers / "7203_トヨタ自動車.md").write_text(
        '---\ncode: "7203"\nclose_date: "2026-09-16"\nper_forecast: 15.0\n---\n\n本文\n',
        encoding="utf-8",
    )
    brand_notes_service.clear_cache()

    record = await pit_provider.VaultFrontmatterProvider().fetch("7203")

    assert record is not None
    assert record.data_as_of == "2026-09-16"


async def test_vault_frontmatter_provider_none_when_note_missing(vault_dirs: VaultDirs) -> None:
    brand_notes_service.clear_cache()
    record = await pit_provider.VaultFrontmatterProvider().fetch("9999")
    assert record is None


def test_default_providers_starts_with_vault_frontmatter() -> None:
    assert pit_provider.DEFAULT_PROVIDERS[0].source_id == "vault_frontmatter"
