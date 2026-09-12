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


async def _fake_fetch_training_ohlcv(ticker: str, period: str = "5y") -> tuple[pd.DataFrame, str]:  # noqa: ARG001
    """`fetch_training_ohlcv`（🆕 P14、🔧 P17でデータソース付きに変更）のフェイク.

    銘柄ごとに再現可能な OHLCV と、固定のデータソース（"yfinance"）を返す。
    """
    return _make_ohlcv(seed=abs(hash(ticker)) % 1000), "yfinance"


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

    async def _stock_data(ticker: str, period: str = "5y") -> tuple[pd.DataFrame, str]:  # noqa: ARG001
        if ticker == "1111":
            return pd.DataFrame(), "yfinance"  # 空データ → ValueError → failed 扱い
        return _make_ohlcv(seed=abs(hash(ticker)) % 1000), "yfinance"

    monkeypatch.setattr(svc, "fetch_training_ohlcv", _stock_data)

    summary = await svc.run_daily_training_batch("xgboost")

    assert summary.trained_this_call == 1
    assert summary.failed_this_call == 1
    assert await model_registry_db.get_champion("xgboost:2222") is not None
    assert await model_registry_db.get_champion("xgboost:1111") is None


# ---------------------------------------------------------------------------
# 🆕 P14: 手動トリガー向け override（daily_limit_override / max_duration_override）
# ---------------------------------------------------------------------------


async def test_override_none_preserves_existing_behavior(migrated_db: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """override 未指定（celery-beat の自動定期実行）は既存の _daily_ticker_limit のまま."""
    universe = [TickerInfo(code=c, name=c, sector=None) for c in ["1111", "2222", "3333"]]
    monkeypatch.setattr(svc, "_get_ticker_master", _async_return(universe))
    monkeypatch.setattr(svc, "fetch_training_ohlcv", _fake_fetch_training_ohlcv)
    monkeypatch.setattr(svc, "_daily_ticker_limit", lambda model_type: 2)

    summary = await svc.run_daily_training_batch("xgboost")

    assert summary.trained_this_call == 2
    assert summary.quota_reached is True


async def test_daily_limit_override_lets_manual_trigger_exceed_settings_limit(
    migrated_db: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """手動トリガー（🆕 P14）は override で settings 由来の上限を超えて全銘柄まで学習できる."""
    universe = [TickerInfo(code=c, name=c, sector=None) for c in ["1111", "2222", "3333"]]
    monkeypatch.setattr(svc, "_get_ticker_master", _async_return(universe))
    monkeypatch.setattr(svc, "fetch_training_ohlcv", _fake_fetch_training_ohlcv)
    monkeypatch.setattr(svc, "_daily_ticker_limit", lambda model_type: 2)  # 自動定期実行の上限（無視されるはず）

    summary = await svc.run_daily_training_batch("xgboost", daily_limit_override=10)

    assert summary.trained_this_call == 3  # 3銘柄全て学習（settings の 2 件上限を超える）
    assert summary.quota_reached is False


async def test_max_duration_override_stops_batch_early(migrated_db: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    universe = [TickerInfo(code=c, name=c, sector=None) for c in ["1111", "2222", "3333"]]
    monkeypatch.setattr(svc, "_get_ticker_master", _async_return(universe))
    monkeypatch.setattr(svc, "fetch_training_ohlcv", _fake_fetch_training_ohlcv)

    summary = await svc.run_daily_training_batch("xgboost", daily_limit_override=10, max_duration_override=0.0)

    # time budget が 0 秒のため、1銘柄目のループ判定で即座に打ち切られる。
    assert summary.trained_this_call == 0


@pytest.mark.parametrize(
    ("model_type", "expected_dl"),
    [("xgboost", False), ("random_forest", False), ("lstm", True), ("transformer", True)],
)
def test_manual_full_run_overrides_uses_dl_duration_for_dl_model_types(model_type: str, expected_dl: bool) -> None:
    daily_limit, duration = svc.manual_full_run_overrides(model_type)
    assert daily_limit == svc._MANUAL_FULL_RUN_DAILY_LIMIT
    expected_duration = (
        svc._MANUAL_FULL_RUN_DL_DURATION_SECONDS if expected_dl else svc._MANUAL_FULL_RUN_DURATION_SECONDS
    )
    assert duration == expected_duration


# ---------------------------------------------------------------------------
# 🆕 P14: 再開性（中断→再実行で続きから学習する）
# ---------------------------------------------------------------------------


async def test_interrupted_run_resumes_from_remaining_tickers_on_next_call(
    migrated_db: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """1回目の呼び出しで一部だけ学習→2回目の呼び出しで残りから再開することを固定する.

    サーバ再起動・ブラウザを閉じる等で中断されても、`training_batch_runs`（当日試行済み）+
    `model_registry.trained_at`（銘柄ごとの最終学習日時）を毎回 DB から読み直す設計により、
    再度呼び出すだけで自然に続きから再開する（コード変更不要、この事実をテストで固定する）。
    """
    universe = [TickerInfo(code=c, name=c, sector=None) for c in ["1111", "2222", "3333", "4444"]]
    monkeypatch.setattr(svc, "_get_ticker_master", _async_return(universe))
    monkeypatch.setattr(svc, "fetch_training_ohlcv", _fake_fetch_training_ohlcv)

    # 1回目: 上限 2 件で「中断」をシミュレート（例: サーバ再起動でプロセスが落ちた想定）。
    first = await svc.run_daily_training_batch("xgboost", daily_limit_override=2)
    assert first.trained_this_call == 2
    assert first.quota_reached is True
    first_attempted = await training_batch_db.get_attempted_tickers(today_jst(), "xgboost")
    assert len(first_attempted) == 2

    # 2回目: 同じ当日の呼び出しで、残りの銘柄だけを続きから学習する。
    second = await svc.run_daily_training_batch("xgboost", daily_limit_override=10)
    assert second.trained_this_call == 2  # 残り2銘柄のみ（1回目の2銘柄は再試行しない）

    all_attempted = await training_batch_db.get_attempted_tickers(today_jst(), "xgboost")
    assert all_attempted == {"1111", "2222", "3333", "4444"}
    for code in all_attempted:
        assert await model_registry_db.get_champion(f"xgboost:{code}") is not None


# ---------------------------------------------------------------------------
# 🆕 P17: on_progress コールバック・データソース記録
# ---------------------------------------------------------------------------


async def test_on_progress_emits_running_then_completed_events(
    migrated_db: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    universe = [TickerInfo(code=c, name=c, sector=None) for c in ["1111", "2222"]]
    monkeypatch.setattr(svc, "_get_ticker_master", _async_return(universe))
    monkeypatch.setattr(svc, "fetch_training_ohlcv", _fake_fetch_training_ohlcv)
    monkeypatch.setattr(svc, "_daily_ticker_limit", lambda model_type: 10)

    events: list[svc.TrainingProgressEvent] = []
    await svc.run_daily_training_batch("xgboost", on_progress=events.append)

    running = [e for e in events if e.status == "running"]
    completed = [e for e in events if e.status == "completed"]
    assert [e.ticker for e in running] == ["1111", "2222"]
    assert [e.ticker for e in completed] == ["1111", "2222"]
    assert all(e.total == 2 for e in events)
    assert [e.processed for e in completed] == [1, 2]
    assert all(e.activated for e in completed)  # 学習可能な系列のため品質ゲートを通過する
    assert all(e.data_source == "yfinance" for e in completed)


async def test_on_progress_emits_failed_status_without_activation(
    migrated_db: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    universe = [TickerInfo(code=c, name=c, sector=None) for c in ["1111"]]
    monkeypatch.setattr(svc, "_get_ticker_master", _async_return(universe))

    async def _empty(_ticker: str, period: str = "5y") -> tuple[pd.DataFrame, str]:  # noqa: ARG001
        return pd.DataFrame(), "yfinance"

    monkeypatch.setattr(svc, "fetch_training_ohlcv", _empty)

    events: list[svc.TrainingProgressEvent] = []
    await svc.run_daily_training_batch("xgboost", on_progress=events.append)

    failed = [e for e in events if e.status == "failed"]
    assert len(failed) == 1
    assert failed[0].activated is False
    assert failed[0].data_source is None


async def test_successful_training_records_data_source(migrated_db: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """学習成功時の `training_batch_runs.data_source` が集計クエリから引けることを確認する."""
    universe = [TickerInfo(code=c, name=c, sector=None) for c in ["1111"]]
    monkeypatch.setattr(svc, "_get_ticker_master", _async_return(universe))

    async def _jquants_sourced(_ticker: str, period: str = "5y") -> tuple[pd.DataFrame, str]:  # noqa: ARG001
        return _make_ohlcv(seed=1), "jquants"

    monkeypatch.setattr(svc, "fetch_training_ohlcv", _jquants_sourced)

    await svc.run_daily_training_batch("xgboost")

    breakdown = await training_batch_db.get_latest_data_source_by_model_type()
    assert breakdown["xgboost"] == {"jquants": 1}
