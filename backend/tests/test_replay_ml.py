"""過去日リプレイの断面プールモデル（🆕 P37）の検証.

特徴量は銘柄ごとに全期間を 1 回だけ計算してキャッシュし、日付で切り出して使う（毎日
ユニバース全体を再計算すると 950 日 × 4000 銘柄で数十時間かかるため）。これが正しいのは
`build_feature_matrix` が過去方向のみの計算（因果的）である場合に限られるので、その前提を
ここでテストとして固定する。
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from backend.services.learning.feature_engineering import build_feature_matrix
from backend.services.replay import ml
from backend.services.replay import price_store as ps

_N_DAYS = 220
_N_CODES = 30


def _dates() -> list[str]:
    return [d.strftime("%Y-%m-%d") for d in pd.bdate_range("2021-01-04", periods=_N_DAYS)]


def _synthetic_store(seed: int = 0) -> ps.PriceStore:
    rng = np.random.default_rng(seed)
    rows: list[dict[str, object]] = []
    for i in range(_N_CODES):
        code = f"{1000 + i}0"
        drift = (i - _N_CODES / 2) * 0.0004  # 銘柄ごとに異なるドリフト（断面で学習できる信号）
        close = 1000.0 * np.exp(np.cumsum(rng.normal(drift, 0.02, _N_DAYS)))
        for d, c in zip(_dates(), close, strict=True):
            rows.append(
                {"Date": d, "Code": code, "AdjO": c, "AdjH": c * 1.01, "AdjL": c * 0.99, "AdjC": c, "AdjVo": 1e5}
            )
    return ps.PriceStore(pd.DataFrame(rows))


def test_feature_matrix_is_causal() -> None:
    """途中で打ち切った系列の最終行の特徴量 == 全期間で計算した同日の特徴量（未来を参照しない）."""
    df = _synthetic_store().view(_dates()[-1]).history("1000")
    full, _ = build_feature_matrix(df, predict_mode=True)

    for cut in (100, 150, _N_DAYS - 5):
        truncated, _ = build_feature_matrix(df.iloc[:cut], predict_mode=True)
        ts = truncated.index[-1]
        pd.testing.assert_series_equal(truncated.loc[ts], full.loc[ts], check_names=False, rtol=1e-9)


def test_feature_cache_rows_for_future_date_raises() -> None:
    store = _synthetic_store()
    cache = ml.FeatureCache.build(store)
    dates = _dates()
    view = store.view(dates[150])

    rows = cache.rows_for_date(view, dates[150])
    assert len(rows) == _N_CODES
    assert set(rows["date"]) == {dates[150]}
    with pytest.raises(ps.FutureDataAccessError):
        cache.rows_for_date(view, dates[151])


def test_training_dates_leave_room_for_label_horizon() -> None:
    """学習に使う日付 t は「t + horizon 営業日」がリプレイ日以前に収まるものだけ（ラベルの未来リーク防止）."""
    store = _synthetic_store()
    dates = _dates()
    view = store.view(dates[200])
    cfg = ml.ReplayMlConfig(horizon=10, window_bdays=120, stride_bdays=5, resolve_buffer_bdays=3)

    picked = ml.training_dates(view, cfg)

    assert picked, "学習日が空"
    assert max(dates.index(d) for d in picked) + cfg.horizon <= 200
    assert picked[-1] == dates[200 - cfg.horizon - cfg.resolve_buffer_bdays]
    assert dates.index(picked[-1]) - dates.index(picked[0]) < cfg.window_bdays


def test_forward_returns_refuse_to_peek_past_as_of() -> None:
    store = _synthetic_store()
    dates = _dates()
    view = store.view(dates[100])

    ok = ml.forward_returns(view, dates[90], horizon=10)
    assert len(ok) == _N_CODES
    with pytest.raises(ps.FutureDataAccessError):
        ml.forward_returns(view, dates[95], horizon=10)


def test_train_and_score_at_replay_date() -> None:
    store = _synthetic_store()
    cache = ml.FeatureCache.build(store)
    dates = _dates()
    view = store.view(dates[210])
    cfg = ml.ReplayMlConfig(horizon=10, window_bdays=150, stride_bdays=2, resolve_buffer_bdays=3)

    trained = ml.train_at(view, cache, cfg, seed=1)
    assert trained is not None
    clf, metrics = trained
    assert int(metrics["n_train"]) > 0

    provider = ml.score_provider_at(view, cache, clf)
    score, proba = provider(pd.DataFrame(), "1029")
    assert score is not None and 0.0 <= score <= 100.0
    assert proba is not None


def test_train_at_returns_none_when_history_too_short() -> None:
    store = _synthetic_store()
    cache = ml.FeatureCache.build(store)
    view = store.view(_dates()[20])

    assert ml.train_at(view, cache, ml.ReplayMlConfig(), seed=1) is None
