"""pool_training_service（断面プール分類器の学習コア＋オーケストレータ）のテスト.

Market Lens `backend/tests/test_pool_training_service.py` から移植。変更点: オーケストレータ
（`run_pool_training`）の検証を Market Lens の `is_active` フラグ方式から Alpha Forge の
champion/challenger（`model_registry_db`/`model_champions`）へ差し替えた。
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from backend.services.db import model_registry_db
from backend.services.learning import pool_training_service
from backend.services.learning.panel_feature_service import add_ticker_target_encoding
from backend.services.learning.pool_model import POOL_LANE, POOL_MODEL_TYPE
from backend.services.learning.pool_training_service import (
    PoolClassifier,
    _purged_date_split,
    load_pool_classifier,
    run_pool_training,
    train_pool_model,
)


def _synthetic_panel(n_dates: int = 50, n_tickers: int = 20, seed: int = 0) -> pd.DataFrame:
    """label が `signal` 列から学習可能な合成断面パネル.

    signal が高い銘柄ほど label=1・fwd_return が高くなるよう作る（AUC > 0.5・
    十分位スプレッド > 0 を再現できる程度のシグナル）。
    """
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


# ---------------------------------------------------------------------------
# _purged_date_split
# ---------------------------------------------------------------------------


def test_purged_date_split_val_is_trailing_fraction_and_train_is_purged() -> None:
    dates = pd.Series(pd.bdate_range("2025-01-01", periods=40).strftime("%Y-%m-%d"))
    train_mask, val_mask = _purged_date_split(dates, val_fraction=0.25, gap_bdays=10)

    val_dates = sorted(dates[val_mask].unique())
    assert len(val_dates) == 10
    assert val_dates == sorted(dates.unique())[-10:]

    assert not (train_mask & val_mask).any()
    first_val = pd.Timestamp(val_dates[0])
    max_train = pd.Timestamp(max(dates[train_mask]))
    assert max_train < first_val - pd.tseries.offsets.BDay(10)


# ---------------------------------------------------------------------------
# train_pool_model
# ---------------------------------------------------------------------------


def test_train_pool_model_learns_signal_and_reports_metrics() -> None:
    clf, metrics = train_pool_model(_synthetic_panel(), val_fraction=0.2, seed=42)

    assert isinstance(clf, PoolClassifier)
    assert clf.model is not None
    assert "ticker_te" in clf.feature_cols
    assert "label" not in clf.feature_cols and "fwd_return" not in clf.feature_cols

    assert metrics["objective"] == "classification"
    assert int(metrics["n_train"]) > 0 and int(metrics["n_val"]) > 0
    assert float(metrics["auc"]) > 0.5
    assert float(metrics["decile_spread"]) > 0.0
    assert float(metrics["decile_top_mean"]) > float(metrics["decile_bottom_mean"])


def test_train_pool_model_target_encoding_is_train_only_no_leakage() -> None:
    """val 期間だけに存在する銘柄でも ticker_te が生成され（global 平均）、学習は完了する."""
    panel = _synthetic_panel()
    tail_dates = sorted(panel["date"].unique())[-5:]
    newcomer = pd.DataFrame(
        {
            "date": tail_dates,
            "code": ["9999"] * len(tail_dates),
            "sector": ["A"] * len(tail_dates),
            "signal": [0.5] * len(tail_dates),
            "momentum": [0.0] * len(tail_dates),
            "xs_rank_signal": [0.9] * len(tail_dates),
            "label": [1.0] * len(tail_dates),
            "fwd_return": [0.03] * len(tail_dates),
        }
    )
    clf, metrics = train_pool_model(pd.concat([panel, newcomer], ignore_index=True))
    assert clf.model is not None
    assert int(metrics["n_val"]) > 0


def test_train_pool_model_raises_on_too_few_labeled_rows() -> None:
    tiny = _synthetic_panel(n_dates=3, n_tickers=5)
    with pytest.raises(ValueError, match="ラベル付き行が少なすぎ"):
        train_pool_model(tiny)


def test_train_pool_model_ignores_unlabeled_rows() -> None:
    panel = _synthetic_panel()
    panel.loc[panel.sample(frac=0.3, random_state=1).index, "label"] = np.nan
    clf, metrics = train_pool_model(panel)
    assert clf.model is not None
    assert int(metrics["n_train"]) + int(metrics["n_val"]) <= int(panel["label"].notna().sum())


# ---------------------------------------------------------------------------
# PoolClassifier save / load
# ---------------------------------------------------------------------------


def test_pool_classifier_save_load_roundtrip(tmp_path: Path) -> None:
    clf, _ = train_pool_model(_synthetic_panel(), seed=7)
    path = str(tmp_path / "sub" / "pool.joblib")
    clf.save(path)

    loaded = PoolClassifier.load(path)
    assert loaded.feature_cols == clf.feature_cols
    assert loaded.objective == "classification"
    assert "__global__" in clf.ticker_te_map
    assert loaded.ticker_te_map == clf.ticker_te_map

    sample = _synthetic_panel(n_dates=6, n_tickers=8, seed=99)
    sample = add_ticker_target_encoding(sample)
    np.testing.assert_allclose(clf.predict_proba(sample), loaded.predict_proba(sample))


def test_pool_classifier_load_missing_file_raises(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        PoolClassifier.load(str(tmp_path / "nope.joblib"))


# ---------------------------------------------------------------------------
# run_pool_training（オーケストレータ）
# ---------------------------------------------------------------------------


def _async_return(value: object):  # type: ignore[no-untyped-def]
    """`monkeypatch.setattr` 用の「常に value を返す非同期関数」を作る."""

    async def _fn(*_args: object, **_kwargs: object) -> object:
        return value

    return _fn


async def test_run_pool_training_registers_and_bootstraps_champion(
    migrated_db: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(pool_training_service, "_MODEL_DIR", tmp_path / "models")
    panel = _synthetic_panel(n_dates=60, n_tickers=20)
    monkeypatch.setattr(pool_training_service, "build_panel", _async_return(panel))

    summary = await run_pool_training(as_of_dates=["2025-01-02"])

    assert summary.status == "trained"
    assert (summary.version or "").startswith("pool-")
    assert summary.is_champion is True

    row = await model_registry_db.get_model(str(summary.version))
    assert row is not None
    assert row["model_type"] == POOL_MODEL_TYPE
    assert row["ticker"] == "__pool__"
    assert row["objective"] == "classification"
    assert Path(str(row["artifact_path"])).exists()

    assert await model_registry_db.get_champion(POOL_LANE) == summary.version


async def test_run_pool_training_records_pit_coverage_when_present_on_panel_attrs(
    migrated_db: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """🆕 P29: `build_panel` が `panel.attrs["pit_coverage"]` を付けていれば val_metrics へ転記されること."""
    import json

    monkeypatch.setattr(pool_training_service, "_MODEL_DIR", tmp_path / "models")
    panel = _synthetic_panel(n_dates=60, n_tickers=20)
    panel.attrs["pit_coverage"] = {"pit_fundamental": {"covered_days": 0, "included": False}}
    monkeypatch.setattr(pool_training_service, "build_panel", _async_return(panel))

    summary = await run_pool_training(as_of_dates=["2025-01-02"])

    row = await model_registry_db.get_model(str(summary.version))
    assert row is not None
    val_metrics = json.loads(str(row["val_metrics"]))
    assert val_metrics["pit_coverage"] == {"pit_fundamental": {"covered_days": 0, "included": False}}


async def test_run_pool_training_omits_pit_coverage_when_absent(
    migrated_db: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """既定（PIT 無効）では `panel.attrs` が空のため val_metrics に `pit_coverage` キーが付かないこと."""
    import json

    monkeypatch.setattr(pool_training_service, "_MODEL_DIR", tmp_path / "models")
    panel = _synthetic_panel(n_dates=60, n_tickers=20)
    monkeypatch.setattr(pool_training_service, "build_panel", _async_return(panel))

    summary = await run_pool_training(as_of_dates=["2025-01-02"])

    row = await model_registry_db.get_model(str(summary.version))
    assert row is not None
    val_metrics = json.loads(str(row["val_metrics"]))
    assert "pit_coverage" not in val_metrics


async def test_run_pool_training_second_version_does_not_replace_champion(
    migrated_db: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(pool_training_service, "_MODEL_DIR", tmp_path / "models")
    panel = _synthetic_panel(n_dates=60, n_tickers=20)
    monkeypatch.setattr(pool_training_service, "build_panel", _async_return(panel))

    first = await run_pool_training(as_of_dates=["2025-01-02"])
    second = await run_pool_training(as_of_dates=["2025-01-02"], seed=99)

    assert first.is_champion is True
    assert second.is_champion is False
    assert await model_registry_db.get_champion(POOL_LANE) == first.version
    versions = await model_registry_db.list_versions_by_model_type(POOL_MODEL_TYPE)
    assert set(versions) == {first.version, second.version}


async def test_run_pool_training_skips_when_panel_has_too_few_labels(
    migrated_db: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    thin = _synthetic_panel(n_dates=3, n_tickers=4)
    monkeypatch.setattr(pool_training_service, "build_panel", _async_return(thin))

    summary = await run_pool_training(as_of_dates=["2025-01-02"])

    assert summary.status == "skipped"
    assert summary.version is None
    assert await model_registry_db.list_versions_by_model_type(POOL_MODEL_TYPE) == []


async def test_run_pool_training_skips_on_empty_panel(migrated_db: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(pool_training_service, "build_panel", _async_return(pd.DataFrame()))

    summary = await run_pool_training(as_of_dates=["2025-01-02"])

    assert summary.status == "skipped"
    assert summary.n_panel_rows == 0


async def test_load_pool_classifier_round_trips_via_registry(
    migrated_db: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(pool_training_service, "_MODEL_DIR", tmp_path / "models")
    panel = _synthetic_panel(n_dates=60, n_tickers=20)
    monkeypatch.setattr(pool_training_service, "build_panel", _async_return(panel))

    summary = await run_pool_training(as_of_dates=["2025-01-02"])

    loaded = await load_pool_classifier(str(summary.version))
    assert loaded.model is not None
    assert loaded.feature_cols


async def test_load_pool_classifier_unknown_version_raises(migrated_db: Path) -> None:
    with pytest.raises(ValueError, match="未登録"):
        await load_pool_classifier("does-not-exist")
