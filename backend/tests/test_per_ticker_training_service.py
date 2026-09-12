"""per_ticker_training_service（銘柄別モデル日次学習バッチ、P9）のテスト.

`run_daily_training_batch` は実際の XGBoost 学習を回す統合テストとして書く（高速なため）。
LSTM/Transformer 固有の分岐（torch 学習）は per_ticker_predictor/dl 側で個別にテスト済みのため
ここでは対象外とし、モデルタイプ非依存のオーケストレーション（候補選定・品質ゲート・
当日上限・監査ログ記録）のみを xgboost で検証する。
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import TypeVar

import numpy as np
import pandas as pd
import pytest

from backend.models.stocks import TickerInfo
from backend.services.db import model_registry_db, training_batch_db
from backend.services.jst_time import today_jst
from backend.services.learning import per_ticker_training_service as svc

_T = TypeVar("_T")


def _async_return(value: _T) -> Callable[..., Awaitable[_T]]:
    async def _fn(*_args: object, **_kwargs: object) -> _T:
        return value

    return _fn


async def _fake_fetch_training_ohlcv(ticker: str, period: str = "5y") -> pd.DataFrame:  # noqa: ARG001
    """`fetch_training_ohlcv`（🆕 P14）のフェイク: 銘柄ごとに再現可能な OHLCV を返す."""
    return _make_ohlcv(seed=abs(hash(ticker)) % 1000)


def _make_ohlcv(n: int = 300, seed: int = 42) -> pd.DataFrame:
    """再現可能・学習可能な（＝ナイーブ予測を上回れる）OHLCV データフレームを生成する.

    純粋なランダムウォークだと本質的に予測不能で、まともに学習しても
    held-out skill が0以下になり品質ゲート（`_apply_quality_gate`）が正しく却下してしまう
    （それ自体は正しい挙動だが、ここでは品質ゲートの「合格して champion 化される」経路を
    検証したいため、周期的なパターン + 小さいノイズで XGBoost が学習可能な系列にする）。
    """
    rng = np.random.default_rng(seed)
    dates = pd.bdate_range("2023-01-01", periods=n)
    t = np.arange(n)
    close = 1000.0 + 50.0 * np.sin(2 * np.pi * t / 20.0) + rng.normal(0, 0.5, size=n)
    high = close + rng.uniform(0, 1, size=n)
    low = close - rng.uniform(0, 1, size=n)
    open_ = close + rng.uniform(-0.5, 0.5, size=n)
    volume = rng.uniform(1_000_000, 5_000_000, size=n)
    return pd.DataFrame({"Open": open_, "High": high, "Low": low, "Close": close, "Volume": volume}, index=dates)


# ---------------------------------------------------------------------------
# _select_candidates
# ---------------------------------------------------------------------------


async def test_select_candidates_prioritizes_untrained_then_oldest(
    migrated_db: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    universe = [TickerInfo(code=c, name=c, sector=None) for c in ["1111", "2222", "3333"]]
    monkeypatch.setattr(svc, "_get_ticker_master", _async_return(universe))

    await model_registry_db.upsert_model(
        version="v1", model_type="xgboost", ticker="2222", objective="regression", trained_at="2026-09-01T00:00:00"
    )
    await model_registry_db.upsert_model(
        version="v2", model_type="xgboost", ticker="3333", objective="regression", trained_at="2026-09-05T00:00:00"
    )

    candidates = await svc._select_candidates(set(), "xgboost")

    # 1111 は未学習（最優先）、2222 は最も古い学習、3333 は最も新しい学習
    assert candidates == ["1111", "2222", "3333"]


async def test_select_candidates_excludes_attempted_today(migrated_db: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    universe = [TickerInfo(code=c, name=c, sector=None) for c in ["1111", "2222"]]
    monkeypatch.setattr(svc, "_get_ticker_master", _async_return(universe))

    candidates = await svc._select_candidates({"1111"}, "xgboost")

    assert candidates == ["2222"]


# ---------------------------------------------------------------------------
# _apply_quality_gate
# ---------------------------------------------------------------------------


async def test_quality_gate_adopts_first_model_for_ticker_unconditionally(migrated_db: Path) -> None:
    await model_registry_db.upsert_model(
        version="v1",
        model_type="xgboost",
        ticker="7203",
        objective="regression",
        val_metrics={"rmse": 0.02, "skill": 0.1},
    )

    adopted = await svc._apply_quality_gate("7203", "xgboost", "v1", {"rmse": 0.02, "skill": 0.1}, df=None)

    assert adopted is True
    assert await model_registry_db.get_champion("xgboost:7203") == "v1"


async def test_quality_gate_rejects_when_skill_non_positive(migrated_db: Path) -> None:
    await model_registry_db.upsert_model(
        version="v1",
        model_type="xgboost",
        ticker="7203",
        objective="regression",
        val_metrics={"rmse": 0.02, "skill": -0.1},
    )

    adopted = await svc._apply_quality_gate("7203", "xgboost", "v1", {"rmse": 0.02, "skill": -0.1}, df=None)

    assert adopted is False
    assert await model_registry_db.get_champion("xgboost:7203") is None


async def test_quality_gate_rejects_worse_challenger_falling_back_to_recorded_rmse(migrated_db: Path) -> None:
    # 既存 champion（artifact_path="" のため _reevaluate_existing_on_window は必ず None を
    # 返し、記録済み val_metrics の rmse へフォールバックする）。
    await model_registry_db.upsert_model(
        version="existing",
        model_type="xgboost",
        ticker="7203",
        objective="regression",
        artifact_path="",
        val_metrics={"rmse": 0.01, "skill": 0.2},
    )
    await svc._apply_quality_gate("7203", "xgboost", "existing", {"rmse": 0.01, "skill": 0.2}, df=None)

    challenger_metrics: dict[str, float | str | int | bool] = {
        "rmse": 0.05,
        "skill": 0.1,
        "eval_start": "2026-01-01",
        "eval_end": "2026-02-01",
    }
    await model_registry_db.upsert_model(
        version="challenger",
        model_type="xgboost",
        ticker="7203",
        objective="regression",
        val_metrics=challenger_metrics,
    )
    adopted = await svc._apply_quality_gate("7203", "xgboost", "challenger", challenger_metrics, df=None)

    assert adopted is False
    assert await model_registry_db.get_champion("xgboost:7203") == "existing"


async def test_quality_gate_adopts_better_or_equal_challenger(migrated_db: Path) -> None:
    await model_registry_db.upsert_model(
        version="existing",
        model_type="xgboost",
        ticker="7203",
        objective="regression",
        artifact_path="",
        val_metrics={"rmse": 0.05, "skill": 0.1},
    )
    await svc._apply_quality_gate("7203", "xgboost", "existing", {"rmse": 0.05, "skill": 0.1}, df=None)

    challenger_metrics: dict[str, float | str | int | bool] = {
        "rmse": 0.01,
        "skill": 0.2,
        "eval_start": "2026-01-01",
        "eval_end": "2026-02-01",
    }
    await model_registry_db.upsert_model(
        version="challenger",
        model_type="xgboost",
        ticker="7203",
        objective="regression",
        val_metrics=challenger_metrics,
    )
    adopted = await svc._apply_quality_gate("7203", "xgboost", "challenger", challenger_metrics, df=None)

    assert adopted is True
    assert await model_registry_db.get_champion("xgboost:7203") == "challenger"


# ---------------------------------------------------------------------------
# run_daily_training_batch（統合。xgboost のみで検証、モデルタイプ非依存の
# オーケストレーションを確認する）
# ---------------------------------------------------------------------------


async def test_run_daily_training_batch_trains_and_activates_untrained_tickers(
    migrated_db: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    universe = [TickerInfo(code=c, name=c, sector=None) for c in ["1111", "2222"]]
    monkeypatch.setattr(svc, "_get_ticker_master", _async_return(universe))
    monkeypatch.setattr(svc, "fetch_training_ohlcv", _fake_fetch_training_ohlcv)
    monkeypatch.setattr(svc, "_daily_ticker_limit", lambda model_type: 10)

    summary = await svc.run_daily_training_batch("xgboost")

    assert summary.trained_this_call == 2
    assert summary.failed_this_call == 0
    assert summary.quota_reached is False
    for code in ("1111", "2222"):
        assert await model_registry_db.get_champion(f"xgboost:{code}") is not None

    attempted = await training_batch_db.get_attempted_tickers(today_jst(), "xgboost")
    assert attempted == {"1111", "2222"}


async def test_run_daily_training_batch_stops_at_daily_limit(
    migrated_db: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    universe = [TickerInfo(code=c, name=c, sector=None) for c in ["1111", "2222", "3333"]]
    monkeypatch.setattr(svc, "_get_ticker_master", _async_return(universe))
    monkeypatch.setattr(svc, "fetch_training_ohlcv", _fake_fetch_training_ohlcv)
    monkeypatch.setattr(svc, "_daily_ticker_limit", lambda model_type: 2)

    summary = await svc.run_daily_training_batch("xgboost")

    assert summary.trained_this_call == 2
    assert summary.quota_reached is True


async def test_run_daily_training_batch_skips_when_quota_already_reached(
    migrated_db: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(svc, "_daily_ticker_limit", lambda model_type: 1)
    await training_batch_db.insert_training_batch_run(
        run_date=today_jst(), ticker="1111", model_type="xgboost", status="completed"
    )

    called = False

    async def _fail_if_called(*_args: object, **_kwargs: object) -> list[TickerInfo]:
        nonlocal called
        called = True
        return []

    monkeypatch.setattr(svc, "_get_ticker_master", _fail_if_called)

    summary = await svc.run_daily_training_batch("xgboost")

    assert summary.quota_reached is True
    assert summary.trained_this_call == 0
    assert called is False


async def test_run_daily_training_batch_records_failure_without_stopping_others(
    migrated_db: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    universe = [TickerInfo(code=c, name=c, sector=None) for c in ["1111", "2222"]]
    monkeypatch.setattr(svc, "_get_ticker_master", _async_return(universe))
    monkeypatch.setattr(svc, "_daily_ticker_limit", lambda model_type: 10)

    async def _stock_data(ticker: str, period: str = "5y") -> pd.DataFrame:  # noqa: ARG001
        if ticker == "1111":
            return pd.DataFrame()  # 空データ → ValueError → failed 扱い
        return _make_ohlcv(seed=abs(hash(ticker)) % 1000)

    monkeypatch.setattr(svc, "fetch_training_ohlcv", _stock_data)

    summary = await svc.run_daily_training_batch("xgboost")

    assert summary.trained_this_call == 1
    assert summary.failed_this_call == 1
    assert await model_registry_db.get_champion("xgboost:2222") is not None
    assert await model_registry_db.get_champion("xgboost:1111") is None
