"""ml_score_provider（断面プールモデルを MlScoreProvider として配線する層）のテスト."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from backend.services.db import model_registry_db
from backend.services.learning.panel_feature_service import PanelContext
from backend.services.learning.pool_model import POOL_LANE
from backend.services.learning.pool_training_service import PoolClassifier, train_pool_model
from backend.services.scoring.ml_score_provider import (
    load_champion_pool_classifier,
    make_pool_ml_score_provider,
)


def _synthetic_panel(n_dates: int = 50, n_tickers: int = 20, seed: int = 0) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    dates = pd.bdate_range("2025-01-01", periods=n_dates).strftime("%Y-%m-%d")
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
                    "sector": "A",
                    "signal": float(signals[i]),
                    "xs_rank_signal": 0.0,
                    "label": 1.0 if score[i] >= thresh else 0.0,
                    "fwd_return": float(0.02 * signals[i]),
                }
            )
    panel = pd.DataFrame(rows)
    panel["xs_rank_signal"] = panel.groupby("date")["signal"].rank(pct=True)
    return panel


def _trained_classifier() -> PoolClassifier:
    clf, _ = train_pool_model(_synthetic_panel(), seed=1)
    return clf


def _ctx_with_codes(codes: list[str], **extra_cols: list[str]) -> PanelContext:
    data: dict[str, list[object]] = {"signal": [0.1] * len(codes), "xs_rank_signal": [0.5] * len(codes)}
    for key, values in extra_cols.items():
        data[key] = list(values)
    frame = pd.DataFrame(data, index=pd.Index(codes, name="code"))
    return PanelContext(as_of="2025-06-01", frame=frame)


def test_provider_returns_none_when_classifier_is_none() -> None:
    provider = make_pool_ml_score_provider(_ctx_with_codes(["7203"]), None)
    assert provider(pd.DataFrame(), "7203") == (None, None)


def test_provider_returns_none_when_ticker_not_in_universe() -> None:
    clf = _trained_classifier()
    provider = make_pool_ml_score_provider(_ctx_with_codes(["1000"]), clf)
    assert provider(pd.DataFrame(), "9999") == (None, None)


def test_provider_scores_ticker_in_universe() -> None:
    clf = _trained_classifier()
    ctx = _ctx_with_codes(["1000"], sector=["A"])
    provider = make_pool_ml_score_provider(ctx, clf)

    score, proba = provider(pd.DataFrame(), "1000")

    assert score is not None and proba is not None
    assert 0.0 <= score <= 100.0
    assert 0.0 <= proba <= 1.0
    assert score == pytest.approx(proba * 100.0)


def test_provider_falls_back_to_none_when_predict_proba_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    clf = _trained_classifier()
    ctx = _ctx_with_codes(["1000"], sector=["A"])

    def _boom(_x: object) -> None:
        raise RuntimeError("inference failed")

    monkeypatch.setattr(clf, "predict_proba", _boom)
    provider = make_pool_ml_score_provider(ctx, clf)

    assert provider(pd.DataFrame(), "1000") == (None, None)


async def test_load_champion_pool_classifier_returns_none_without_champion(migrated_db: Path) -> None:
    assert await load_champion_pool_classifier() is None


async def test_load_champion_pool_classifier_loads_registered_champion(
    migrated_db: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from backend.services.learning import pool_training_service

    monkeypatch.setattr(pool_training_service, "_MODEL_DIR", tmp_path / "models")
    panel = _synthetic_panel(n_dates=60, n_tickers=20)

    async def _fake_build_panel(*_args: object, **_kwargs: object) -> pd.DataFrame:
        return panel

    monkeypatch.setattr(pool_training_service, "build_panel", _fake_build_panel)

    summary = await pool_training_service.run_pool_training(as_of_dates=["2025-01-02"])
    assert summary.is_champion is True
    assert await model_registry_db.get_champion(POOL_LANE) == summary.version

    loaded = await load_champion_pool_classifier()
    assert loaded is not None
    assert loaded.model is not None
