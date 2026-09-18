"""ソースアブレーション評価（🆕 P29、`source_ablations` 初実装）の検証."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from backend.services.db import source_ablation_db
from backend.services.learning import pit_feature_service as pit_fs
from backend.services.ledger import ablation_service


def _synthetic_panel(n_dates: int = 50, n_tickers: int = 20, seed: int = 0) -> pd.DataFrame:
    """`test_pool_training_service._synthetic_panel` と同型の合成断面パネル（label 学習可能）."""
    rng = np.random.default_rng(seed)
    dates = pd.bdate_range("2025-01-01", periods=n_dates).strftime("%Y-%m-%d")
    sectors = ["A", "B", "C"]
    rows = []
    for d in dates:
        signals = rng.normal(size=n_tickers)
        noise = rng.normal(scale=0.6, size=n_tickers)
        score = signals + noise
        thresh = np.quantile(score, 0.8)
        for i in range(n_tickers):
            rows.append(
                {
                    "date": d,
                    "code": f"{1000 + i:04d}",
                    "sector": sectors[i % len(sectors)],
                    "signal": float(signals[i]),
                    "momentum": float(rng.normal()),
                    "xs_rank_signal": 0.0,
                    "label": 1.0 if score[i] >= thresh else 0.0,
                    "fwd_return": float(0.02 * signals[i] + rng.normal(scale=0.01)),
                }
            )
    panel = pd.DataFrame(rows)
    panel["xs_rank_signal"] = panel.groupby("date")["signal"].rank(pct=True)
    return panel


def _panel_with_fundamental_pit(**kwargs: object) -> pd.DataFrame:
    panel = _synthetic_panel(**kwargs)  # type: ignore[arg-type]
    panel["per_forecast"] = panel["signal"]
    panel["pit_fundamental_staleness_days"] = 0
    panel["xs_rank_per_forecast"] = panel.groupby("date")["per_forecast"].rank(pct=True)
    return panel


# --- _group_columns ---


def test_group_columns_includes_raw_and_derived_but_not_unrelated() -> None:
    panel = pd.DataFrame(columns=["date", "code", "per_forecast", "xs_rank_per_forecast", "pbr", "momentum"])
    cols = ablation_service._group_columns(panel, pit_fs.FUNDAMENTAL_VALUE_COLS)
    assert set(cols) == {"per_forecast", "xs_rank_per_forecast", "pbr"}


def test_group_columns_empty_when_group_absent() -> None:
    panel = pd.DataFrame(columns=["date", "code", "momentum"])
    assert ablation_service._group_columns(panel, pit_fs.FUNDAMENTAL_VALUE_COLS) == []


# --- run_source_ablation ---


async def test_run_source_ablation_returns_none_when_group_absent() -> None:
    result = await ablation_service.run_source_ablation(_synthetic_panel(), excluded_source=pit_fs.FUNDAMENTAL_GROUP)
    assert result is None


async def test_run_source_ablation_unknown_group_raises() -> None:
    with pytest.raises(ValueError, match="未知のアブレーション対象グループ"):
        await ablation_service.run_source_ablation(_synthetic_panel(), excluded_source="bogus")


async def test_run_source_ablation_drops_group_columns_and_computes_deltas() -> None:
    panel = _panel_with_fundamental_pit()

    result = await ablation_service.run_source_ablation(panel, excluded_source=pit_fs.FUNDAMENTAL_GROUP)

    assert result is not None
    assert set(result.dropped_columns) == {"per_forecast", "pit_fundamental_staleness_days", "xs_rank_per_forecast"}
    assert "auc" in result.deltas
    assert "brier_skill" in result.deltas
    assert result.sample_n > 0


async def test_run_source_ablation_excluded_model_does_not_see_dropped_columns(monkeypatch: pytest.MonkeyPatch) -> None:
    """除外パネルが実際に `train_pool_model` へ渡る際、対象列を含んでいないことを直接検証する."""
    import backend.services.ledger.ablation_service as mod

    seen_columns: list[list[str]] = []
    original = mod.train_pool_model

    def _spy(panel: pd.DataFrame, **kwargs: object) -> object:
        seen_columns.append(list(panel.columns))
        return original(panel, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(mod, "train_pool_model", _spy)

    panel = _panel_with_fundamental_pit()
    await ablation_service.run_source_ablation(panel, excluded_source=pit_fs.FUNDAMENTAL_GROUP)

    assert "per_forecast" in seen_columns[0]  # baseline（全部入り）には残っている
    assert "per_forecast" not in seen_columns[1]  # excluded（除外後）には残っていない
    assert "xs_rank_per_forecast" not in seen_columns[1]


# --- run_all_pit_ablations（永続化込み） ---


async def test_run_all_pit_ablations_persists_rows_for_present_groups_only(migrated_db: Path) -> None:
    panel = _panel_with_fundamental_pit()

    results = await ablation_service.run_all_pit_ablations(panel)

    assert {r.excluded_source for r in results} == {pit_fs.FUNDAMENTAL_GROUP}  # sentiment 列は無いので対象外
    rows = await source_ablation_db.list_ablations()
    assert len(rows) == len(results[0].deltas)
    assert all(r["excluded_source"] == pit_fs.FUNDAMENTAL_GROUP for r in rows)


async def test_run_all_pit_ablations_no_groups_present_persists_nothing(migrated_db: Path) -> None:
    results = await ablation_service.run_all_pit_ablations(_synthetic_panel())

    assert results == []
    assert await source_ablation_db.list_ablations() == []
