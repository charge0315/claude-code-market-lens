"""`model_stats_service`（🆕 P15、学習状態可視化の集計ロジック）の検証.

`model_stats_db` の DB アクセスと `_get_ticker_master`（全銘柄数）はモンキーパッチで
フェイクに差し替え、集計・整形ロジック（lane 解析・champion 数集計・品質値の
異常系フィルタ・学習推移の日付/ステータス集計）のみを検証する。
"""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from typing import TypeVar

import pytest

from backend.models.stocks import TickerInfo
from backend.services.registry import model_stats_service as svc

_T = TypeVar("_T")


def _async_return(value: _T) -> Callable[..., Awaitable[_T]]:
    async def _fn(*_args: object, **_kwargs: object) -> _T:
        return value

    return _fn


_UNIVERSE = [TickerInfo(code=c, name=c, sector=None) for c in ["1111", "2222", "3333"]]


# ---------------------------------------------------------------------------
# _model_type_from_lane / _as_finite_float
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("lane", "expected"),
    [
        ("xgboost:7203", "xgboost"),
        ("lstm:6758", "lstm"),
        ("mid_term", None),  # `:` を含まないシステムレーンは対象外
        ("short_term", None),
        ("ml_pool", None),
        ("unknown_type:7203", None),  # 未知の model_type
    ],
)
def test_model_type_from_lane(lane: str, expected: str | None) -> None:
    assert svc._model_type_from_lane(lane) == expected


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (0.5, 0.5),
        (1, 1.0),
        (True, None),  # bool は int のサブクラスだが数値として扱わない
        (False, None),
        ("0.5", None),  # 文字列は対象外
        (None, None),
        (float("nan"), None),
        (float("inf"), None),
        (float("-inf"), None),
    ],
)
def test_as_finite_float(value: object, expected: float | None) -> None:
    assert svc._as_finite_float(value) == expected


# ---------------------------------------------------------------------------
# build_coverage
# ---------------------------------------------------------------------------


async def test_build_coverage_combines_universe_trained_and_champion_counts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(svc, "_get_ticker_master", _async_return(_UNIVERSE))
    monkeypatch.setattr(
        svc.model_stats_db, "count_trained_tickers_by_model_type", _async_return({"xgboost": 2, "lstm": 1})
    )
    monkeypatch.setattr(
        svc.model_stats_db,
        "list_per_ticker_champion_metrics",
        _async_return(
            [
                {"lane": "xgboost:1111", "val_metrics": "{}"},
                {"lane": "xgboost:2222", "val_metrics": "{}"},
                {"lane": "lstm:1111", "val_metrics": "{}"},
            ]
        ),
    )
    monkeypatch.setattr(
        svc.training_batch_db,
        "get_latest_data_source_by_model_type",
        _async_return({"xgboost": {"yfinance": 1, "jquants": 1}}),
    )
    monkeypatch.setattr(
        svc.model_stats_db,
        "get_last_trained_at_by_model_type",
        _async_return({"xgboost": "2026-09-10T00:00:00"}),
    )

    coverage = await svc.build_coverage()

    by_type = {c.model_type: c for c in coverage}
    assert set(by_type) == {"xgboost", "random_forest", "lstm", "transformer"}
    assert by_type["xgboost"].universe_size == 3
    assert by_type["xgboost"].trained_count == 2
    assert by_type["xgboost"].champion_count == 2
    assert by_type["xgboost"].yfinance_count == 1
    assert by_type["xgboost"].jquants_count == 1
    assert by_type["xgboost"].last_trained_at == "2026-09-10T00:00:00"
    # データソース内訳・最終学習日時が無いモデルタイプは既定値（0/None）で出現する。
    assert by_type["lstm"].yfinance_count == 0
    assert by_type["lstm"].jquants_count == 0
    assert by_type["lstm"].last_trained_at is None
    assert by_type["lstm"].trained_count == 1
    assert by_type["lstm"].champion_count == 1
    # 学習履歴が無いモデルタイプも 0 件として出現する（フロントでの一覧表示のため）。
    assert by_type["random_forest"].trained_count == 0
    assert by_type["random_forest"].champion_count == 0


# ---------------------------------------------------------------------------
# build_quality_distribution
# ---------------------------------------------------------------------------


async def test_build_quality_distribution_extracts_skill_and_rmse_per_model_type(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rows = [
        {"lane": "xgboost:1111", "val_metrics": json.dumps({"skill": 0.1, "rmse": 1.0})},
        {"lane": "xgboost:2222", "val_metrics": json.dumps({"skill": 0.2, "rmse": 2.0})},
        {"lane": "lstm:1111", "val_metrics": json.dumps({"skill": 0.3, "rmse": 3.0})},
    ]
    monkeypatch.setattr(svc.model_stats_db, "list_per_ticker_champion_metrics", _async_return(rows))

    dist = await svc.build_quality_distribution()

    by_type = {d.model_type: d for d in dist}
    assert by_type["xgboost"].skill_scores == [0.1, 0.2]
    assert by_type["xgboost"].rmse_scores == [1.0, 2.0]
    assert by_type["lstm"].skill_scores == [0.3]
    # champion が存在しないモデルタイプは空リストで出現する。
    assert by_type["transformer"].skill_scores == []
    assert by_type["transformer"].rmse_scores == []


async def test_build_quality_distribution_filters_non_finite_and_non_numeric_values(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rows = [
        {"lane": "xgboost:1111", "val_metrics": json.dumps({"skill": float("nan"), "rmse": 1.0})},
        {"lane": "xgboost:2222", "val_metrics": json.dumps({"skill": "not-a-number", "rmse": None})},
        {"lane": "xgboost:3333", "val_metrics": json.dumps({})},  # キー欠落
    ]
    monkeypatch.setattr(svc.model_stats_db, "list_per_ticker_champion_metrics", _async_return(rows))

    dist = await svc.build_quality_distribution()

    xgb = next(d for d in dist if d.model_type == "xgboost")
    assert xgb.skill_scores == []
    assert xgb.rmse_scores == [1.0]


async def test_build_quality_distribution_ignores_lane_with_invalid_json(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rows = [
        {"lane": "xgboost:1111", "val_metrics": "not-json"},
        {"lane": "xgboost:2222", "val_metrics": json.dumps([1, 2, 3])},  # dict でない
        {"lane": "xgboost:3333", "val_metrics": json.dumps({"skill": 0.5, "rmse": 1.5})},
    ]
    monkeypatch.setattr(svc.model_stats_db, "list_per_ticker_champion_metrics", _async_return(rows))

    dist = await svc.build_quality_distribution()

    xgb = next(d for d in dist if d.model_type == "xgboost")
    assert xgb.skill_scores == [0.5]
    assert xgb.rmse_scores == [1.5]


# ---------------------------------------------------------------------------
# build_training_trend
# ---------------------------------------------------------------------------


async def test_build_training_trend_groups_completed_and_failed_by_date_and_type(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rows = [
        {"run_date": "2026-09-10", "model_type": "xgboost", "status": "completed", "n": 5},
        {"run_date": "2026-09-10", "model_type": "xgboost", "status": "failed", "n": 1},
        {"run_date": "2026-09-11", "model_type": "lstm", "status": "completed", "n": 2},
    ]
    monkeypatch.setattr(svc.model_stats_db, "get_training_counts_by_date", _async_return(rows))

    trend = await svc.build_training_trend(days=30)

    by_key = {(t.date, t.model_type): t for t in trend}
    assert by_key[("2026-09-10", "xgboost")].trained_count == 5
    assert by_key[("2026-09-10", "xgboost")].failed_count == 1
    assert by_key[("2026-09-11", "lstm")].trained_count == 2
    assert by_key[("2026-09-11", "lstm")].failed_count == 0


async def test_build_training_trend_ignores_unknown_model_type_and_status(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rows = [
        {"run_date": "2026-09-10", "model_type": "ml_pool", "status": "completed", "n": 9},
        {"run_date": "2026-09-10", "model_type": "xgboost", "status": "skipped", "n": 3},
        {"run_date": "2026-09-10", "model_type": "xgboost", "status": "completed", "n": 4},
    ]
    monkeypatch.setattr(svc.model_stats_db, "get_training_counts_by_date", _async_return(rows))

    trend = await svc.build_training_trend(days=30)

    assert len(trend) == 1
    assert trend[0].model_type == "xgboost"
    assert trend[0].trained_count == 4
    assert trend[0].failed_count == 0
