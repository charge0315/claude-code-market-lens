"""Vaultアーカイブレポート API（`routers/vault_reports.py`）の検証（envelope・保存確認）."""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from backend.services.vault_report import report_generator as rg
from backend.tests.conftest import VaultDirs


@pytest.fixture(autouse=True)
def _fake_price_history(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _fake(_symbol: str, _before_date: str) -> list[tuple[str, float]]:
        return []

    monkeypatch.setattr(rg, "fetch_price_history_before", _fake)


@pytest_asyncio.fixture
async def client(migrated_db: Path, vault_dirs: VaultDirs) -> AsyncIterator[AsyncClient]:
    from backend.main import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac


async def test_generate_returns_envelope_with_report_dir(client: AsyncClient, vault_dirs: VaultDirs) -> None:
    res = await client.post("/api/vault-reports/generate", params={"date": "2026-09-17"})

    assert res.status_code == 200
    body = res.json()
    assert body["success"] is True
    assert body["data"]["report_date"] == "2026-09-17"
    expected_dir = vault_dirs.daily / "AlphaForge" / "2026-09-17"
    assert Path(body["data"]["report_dir"]) == expected_dir
    assert (expected_dir / "report.html").is_file()
