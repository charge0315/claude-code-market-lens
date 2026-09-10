"""ファンダメンタル分析（yfinance + Vault frontmatter フォールバック）の検証."""

from __future__ import annotations

import pytest

from backend.services.scoring import fundamental_analyzer as fa
from backend.services.vault import brand_notes_service
from backend.tests.conftest import VaultDirs


class _FakeTicker:
    def __init__(self, _s: str, info: dict[str, object]) -> None:
        self.info = info


def _patch_yf(monkeypatch: pytest.MonkeyPatch, info: dict[str, object]) -> None:
    monkeypatch.setattr(fa.yf, "Ticker", lambda s: _FakeTicker(s, info))
    monkeypatch.setattr(fa.stock_cache, "get_json", lambda _k: None)
    monkeypatch.setattr(fa.stock_cache, "set_json", lambda *_a, **_k: None)


def test_get_fundamental_data_normalizes_dividend_yield(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_yf(monkeypatch, {"trailingPE": 12.5, "priceToBook": 1.1, "dividendYield": 3.2, "returnOnEquity": 0.12})
    out = fa.get_fundamental_data("7203")
    assert out["per"] == 12.5
    assert out["dividend_yield"] == pytest.approx(0.032)  # 3.2% → 0.032
    assert out["source"] == "yfinance"


def test_per_falls_back_to_forward_pe(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_yf(monkeypatch, {"forwardPE": 15.0})
    assert fa.get_fundamental_data("7203")["per"] == 15.0


async def test_vault_fallback_fills_missing_metrics(monkeypatch: pytest.MonkeyPatch, vault_dirs: VaultDirs) -> None:
    # yfinance は PER のみ返し、PBR / ROE / 配当利回り / 時価総額は欠損。
    _patch_yf(monkeypatch, {"trailingPE": 20.0})
    (vault_dirs.tickers / "7203_トヨタ自動車.md").write_text(
        '---\ncode: "7203"\nname: "トヨタ自動車"\nsector33: "輸送用機器"\n'
        'pbr: 1.05\nroe: 12.5\ndividend_yield_forecast: "3.1%"\nmarket_cap_oku: 480000.0\n---\n\n# 本文は無視\n',
        encoding="utf-8",
    )
    brand_notes_service.clear_cache()

    out = await fa.get_fundamental_with_vault_fallback("7203")
    assert out["per"] == 20.0  # yfinance 側は上書きしない
    assert out["pbr"] == 1.05
    assert out["roe"] == pytest.approx(0.125)  # 12.5% → 0.125
    assert out["dividend_yield"] == pytest.approx(0.031)
    assert out["market_cap"] == pytest.approx(480000.0 * 1e8)
    assert out["source"] == "yfinance+vault"
    assert "pbr" in str(out["vault_filled"])


async def test_vault_fallback_noop_when_note_missing(monkeypatch: pytest.MonkeyPatch, vault_dirs: VaultDirs) -> None:
    _patch_yf(monkeypatch, {"trailingPE": 20.0})
    brand_notes_service.clear_cache()
    out = await fa.get_fundamental_with_vault_fallback("7203")
    assert out["source"] == "yfinance"
