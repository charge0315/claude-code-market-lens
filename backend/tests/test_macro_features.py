"""マクロ指標特徴量サービスの検証（Market Lens から移植、^VIX 代替）."""

from __future__ import annotations

import pandas as pd
import pytest

from backend.services.data import macro_features as mf


def test_derive_macro_period_from_index_span() -> None:
    idx = pd.DatetimeIndex(pd.date_range("2024-01-01", "2026-01-01", freq="D"))
    df = pd.DataFrame(index=idx)
    # 約 2 年（731 日 → ceil = 3）+ バッファ 1 年 = "4y"。
    assert mf.derive_macro_period(df) == "4y"


def test_derive_macro_period_defaults_when_no_datetime_index() -> None:
    assert mf.derive_macro_period(pd.DataFrame()) == "5y"


def test_fetch_macro_features_aligns_returns_to_target_calendar(monkeypatch: pytest.MonkeyPatch) -> None:
    target = pd.DatetimeIndex(pd.to_datetime(["2026-09-08", "2026-09-09", "2026-09-10"]))

    def fake_macro(symbol: str, period: str = "5y", interval: str = "1d") -> pd.DataFrame:  # noqa: ARG001
        # どのシンボルも同じ形の Close 系列を返す（2 日おき → ffill で整列される）。
        return pd.DataFrame(
            {"Close": [100.0, 110.0]},
            index=pd.to_datetime(["2026-09-08", "2026-09-10"]),
        )

    monkeypatch.setattr(mf, "fetch_macro_symbol_data", fake_macro)
    out = mf.fetch_macro_features(target)
    assert list(out.columns) == ["n225_return", "usdjpy_return", "vix_return"]
    assert list(out.index) == list(target)
    # 09-09 は ffill で 100 のまま → pct_change 0.0、09-10 は 110/100-1 = 0.1。
    assert out["vix_return"].iloc[2] == pytest.approx(0.1)


def test_fetch_macro_features_falls_back_to_zero_on_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    target = pd.DatetimeIndex(pd.to_datetime(["2026-09-09", "2026-09-10"]))

    def boom(symbol: str, period: str = "5y", interval: str = "1d") -> pd.DataFrame:  # noqa: ARG001
        raise RuntimeError("rate limited")

    monkeypatch.setattr(mf, "fetch_macro_symbol_data", boom)
    out = mf.fetch_macro_features(target)
    assert (out == 0.0).all().all()
