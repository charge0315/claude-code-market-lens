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
from backend.services.learning import training_target_service

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
    monkeypatch.setattr(svc.training_target_service, "resolve_training_universe", _async_return(universe))

    await model_registry_db.upsert_model(
        version="v1", model_type="xgboost", ticker="2222", objective="regression", trained_at="2026-09-01T00:00:00"
    )
    await model_registry_db.upsert_model(
        version="v2", model_type="xgboost", ticker="3333", objective="regression", trained_at="2026-09-05T00:00:00"
    )

    candidates = await svc._select_candidates(set(), "xgboost")

    # 1111 は未学習（最優先）、2222 は最も古い学習、3333 は最も新しい学習
    assert candidates == ["1111", "2222", "3333"]


async def test_select_candidates_defers_recently_failed_untrained_tickers(
    migrated_db: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """恒常的に失敗する未学習銘柄（上場直後・データ不足等）が毎日最優先で日次枠を食い潰さないこと.

    2026-09-21〜24 に、失敗し続ける約200銘柄が「未学習」扱いで毎日先頭に来て枠（200/40）を
    使い切り、学習済み銘柄の再学習が止まった。失敗日時も「最後に試した日時」として扱う。
    """
    universe = [TickerInfo(code=c, name=c, sector=None) for c in ["1111", "2222", "3333", "4444"]]
    monkeypatch.setattr(svc.training_target_service, "resolve_training_universe", _async_return(universe))

    await model_registry_db.upsert_model(
        version="v1", model_type="xgboost", ticker="2222", objective="regression", trained_at="2026-09-01T00:00:00"
    )
    await model_registry_db.upsert_model(
        version="v2", model_type="xgboost", ticker="3333", objective="regression", trained_at="2026-09-05T00:00:00"
    )
    # 1111 は一度も学習に成功しておらず、直近（現在時刻）で失敗している
    await training_batch_db.insert_training_batch_run(
        run_date="2026-09-06", ticker="1111", model_type="xgboost", status="failed", error="データ不足"
    )

    candidates = await svc._select_candidates(set(), "xgboost")

    # 4444 は一度も試行していない（最優先）、1111 は直近で失敗したため最後尾へ回る
    assert candidates == ["4444", "2222", "3333", "1111"]


async def test_select_candidates_excludes_attempted_today(migrated_db: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    universe = [TickerInfo(code=c, name=c, sector=None) for c in ["1111", "2222"]]
    monkeypatch.setattr(svc.training_target_service, "resolve_training_universe", _async_return(universe))

    candidates = await svc._select_candidates({"1111"}, "xgboost")

    assert candidates == ["2222"]


# ---------------------------------------------------------------------------
# _apply_quality_gate_from_worker_result（🆕 CPU再評価は子プロセス側で完了済みという前提で
# DB read/write のみを行う。旧 _apply_quality_gate の判定ロジック自体は変更していない）
# ---------------------------------------------------------------------------


async def test_quality_gate_adopts_first_model_for_ticker_unconditionally(migrated_db: Path) -> None:
    await model_registry_db.upsert_model(
        version="v1",
        model_type="xgboost",
        ticker="7203",
        objective="regression",
        val_metrics={"rmse": 0.02, "skill": 0.1},
    )

    adopted = await svc._apply_quality_gate_from_worker_result(
        "7203",
        "xgboost",
        "v1",
        {"rmse": 0.02, "skill": 0.1},
        existing_version=None,
        existing_row=None,
        comparison_rmse=None,
    )

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

    adopted = await svc._apply_quality_gate_from_worker_result(
        "7203",
        "xgboost",
        "v1",
        {"rmse": 0.02, "skill": -0.1},
        existing_version=None,
        existing_row=None,
        comparison_rmse=None,
    )

    assert adopted is False
    assert await model_registry_db.get_champion("xgboost:7203") is None


async def test_quality_gate_rejects_worse_challenger_falling_back_to_recorded_rmse(migrated_db: Path) -> None:
    # 子プロセスでの既存championの再評価に失敗した状況を模す（comparison_rmse=None）。
    # この場合は記録済み val_metrics の rmse（0.01）へフォールバックして比較する。
    await model_registry_db.upsert_model(
        version="existing",
        model_type="xgboost",
        ticker="7203",
        objective="regression",
        artifact_path="",
        val_metrics={"rmse": 0.01, "skill": 0.2},
    )
    await model_registry_db.set_champion("xgboost:7203", "existing", promoted_by="quality_gate")
    existing_row = await model_registry_db.get_model("existing")

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
    adopted = await svc._apply_quality_gate_from_worker_result(
        "7203",
        "xgboost",
        "challenger",
        challenger_metrics,
        existing_version="existing",
        existing_row=existing_row,
        comparison_rmse=None,
    )

    assert adopted is False
    assert await model_registry_db.get_champion("xgboost:7203") == "existing"


async def test_quality_gate_adopts_better_or_equal_challenger_using_subprocess_comparison_rmse(
    migrated_db: Path,
) -> None:
    # comparison_rmse（子プロセスが同一窓で再評価した既存championのRMSE）が渡された場合、
    # 記録済み val_metrics の rmse（0.05）ではなくこちらを比較に使うことを確認する。
    await model_registry_db.upsert_model(
        version="existing",
        model_type="xgboost",
        ticker="7203",
        objective="regression",
        artifact_path="",
        val_metrics={"rmse": 0.05, "skill": 0.1},
    )
    existing_row = await model_registry_db.get_model("existing")

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
    adopted = await svc._apply_quality_gate_from_worker_result(
        "7203",
        "xgboost",
        "challenger",
        challenger_metrics,
        existing_version="existing",
        existing_row=existing_row,
        comparison_rmse=0.02,
    )

    assert adopted is True
    assert await model_registry_db.get_champion("xgboost:7203") == "challenger"


async def test_quality_gate_adopts_when_existing_champion_row_missing(migrated_db: Path) -> None:
    """既存 champion のレジストリ行が見つからない（データ不整合）場合は安全側で採用する."""
    await model_registry_db.upsert_model(
        version="new-version", model_type="xgboost", ticker="7203", objective="regression"
    )

    adopted = await svc._apply_quality_gate_from_worker_result(
        "7203",
        "xgboost",
        "new-version",
        {"rmse": 0.05, "skill": 0.1},
        existing_version="missing-version",
        existing_row=None,
        comparison_rmse=None,
    )

    assert adopted is True
    assert await model_registry_db.get_champion("xgboost:7203") == "new-version"


# ---------------------------------------------------------------------------
# run_daily_training_batch（統合。xgboost のみで検証、モデルタイプ非依存の
# オーケストレーションを確認する）
# ---------------------------------------------------------------------------


async def test_run_daily_training_batch_trains_and_activates_untrained_tickers(
    migrated_db: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    universe = [TickerInfo(code=c, name=c, sector=None) for c in ["1111", "2222"]]
    monkeypatch.setattr(svc.training_target_service, "resolve_training_universe", _async_return(universe))
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
    monkeypatch.setattr(svc.training_target_service, "resolve_training_universe", _async_return(universe))
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

    monkeypatch.setattr(svc.training_target_service, "resolve_training_universe", _fail_if_called)

    summary = await svc.run_daily_training_batch("xgboost")

    assert summary.quota_reached is True
    assert summary.trained_this_call == 0
    assert called is False


async def test_run_daily_training_batch_records_failure_without_stopping_others(
    migrated_db: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    universe = [TickerInfo(code=c, name=c, sector=None) for c in ["1111", "2222"]]
    monkeypatch.setattr(svc.training_target_service, "resolve_training_universe", _async_return(universe))
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
    monkeypatch.setattr(svc.training_target_service, "resolve_training_universe", _async_return(universe))
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
    monkeypatch.setattr(svc.training_target_service, "resolve_training_universe", _async_return(universe))
    monkeypatch.setattr(svc, "fetch_training_ohlcv", _fake_fetch_training_ohlcv)
    monkeypatch.setattr(svc, "_daily_ticker_limit", lambda model_type: 2)  # 自動定期実行の上限（無視されるはず）

    summary = await svc.run_daily_training_batch("xgboost", daily_limit_override=10)

    assert summary.trained_this_call == 3  # 3銘柄全て学習（settings の 2 件上限を超える）
    assert summary.quota_reached is False


async def test_max_duration_override_stops_batch_early(migrated_db: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    universe = [TickerInfo(code=c, name=c, sector=None) for c in ["1111", "2222", "3333"]]
    monkeypatch.setattr(svc.training_target_service, "resolve_training_universe", _async_return(universe))
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
    monkeypatch.setattr(svc.training_target_service, "resolve_training_universe", _async_return(universe))
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
    monkeypatch.setattr(svc.training_target_service, "resolve_training_universe", _async_return(universe))
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
    monkeypatch.setattr(svc.training_target_service, "resolve_training_universe", _async_return(universe))

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
    monkeypatch.setattr(svc.training_target_service, "resolve_training_universe", _async_return(universe))

    async def _jquants_sourced(_ticker: str, period: str = "5y") -> tuple[pd.DataFrame, str]:  # noqa: ARG001
        return _make_ohlcv(seed=1), "jquants"

    monkeypatch.setattr(svc, "fetch_training_ohlcv", _jquants_sourced)

    await svc.run_daily_training_batch("xgboost")

    breakdown = await training_batch_db.get_latest_data_source_by_model_type()
    assert breakdown["xgboost"] == {"jquants": 1}


# ---------------------------------------------------------------------------
# 🆕 並列学習（ProcessPoolExecutor、学習対象設定の max_parallel_workers）
# ---------------------------------------------------------------------------


async def test_create_worker_pool_builds_process_pool_executor_with_requested_size(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """本番経路の `_create_worker_pool` が `ProcessPoolExecutor` を返すことを確認する.

    autouse fixture（`_use_thread_pool_for_training_batch`）が `monkeypatch` を共有するため、
    ここで一度 undo して素の実装（本番相当）へ戻してから呼び出す。
    """
    from concurrent.futures import ProcessPoolExecutor

    monkeypatch.undo()

    pool = svc._create_worker_pool(3)
    assert isinstance(pool, ProcessPoolExecutor)
    try:
        assert pool._max_workers == 3  # type: ignore[attr-defined] # noqa: SLF001 - 実際に指定サイズで生成されたことの確認用
    finally:
        pool.shutdown(wait=False, cancel_futures=True)


def _without_project_root(paths: list[str]) -> list[str]:
    root = Path(svc._PROJECT_ROOT)
    return [p for p in paths if Path(p or ".").resolve() != root]


def test_ensure_project_root_on_sys_path_inserts_when_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    """親の `sys.path` にプロジェクトルートが無ければ先頭へ追加する.

    `celery.exe` は `-A backend.celery_app` の import 中だけ `cwd_in_path()` で cwd を
    `sys.path` へ足し、import 後に外す。spawn の子プロセスは起動直後に `sys.path` を
    親のコピーで丸ごと上書きするため、`PYTHONPATH` 環境変数で足しても消されてしまい
    `ModuleNotFoundError: No module named 'backend'` になる（2026-09-23 に再発・特定）。
    """
    import sys

    monkeypatch.setattr(sys, "path", _without_project_root(list(sys.path)))

    svc._ensure_project_root_on_sys_path()

    assert sys.path[0] == str(svc._PROJECT_ROOT)


def test_ensure_project_root_on_sys_path_is_idempotent(monkeypatch: pytest.MonkeyPatch) -> None:
    """既にプロジェクトルートが含まれていれば重複追加しない."""
    import sys

    monkeypatch.setattr(sys, "path", [str(svc._PROJECT_ROOT), *_without_project_root(list(sys.path))])

    svc._ensure_project_root_on_sys_path()
    svc._ensure_project_root_on_sys_path()

    assert sys.path.count(str(svc._PROJECT_ROOT)) == 1


def test_create_worker_pool_child_can_import_backend_under_celery_like_sys_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """celery.exe 相当（親 `sys.path` にルート無し）でも spawn 子プロセスが `backend` を import できる.

    実プロセスを spawn する回帰テスト。修正前（`PYTHONPATH` 方式）はこのテストが
    `BrokenProcessPool` で失敗する。
    """
    import importlib.util
    import os
    import sys

    # autouse fixture がスレッドプールへ差し替えているため、素の実装へ戻す
    monkeypatch.undo()
    monkeypatch.setattr(sys, "path", _without_project_root(list(sys.path)))
    monkeypatch.delenv("PYTHONPATH", raising=False)
    # 子プロセスの cwd 経由で偶然 import できてしまわないよう、ルート外へ移動する
    monkeypatch.chdir(Path(os.sep))

    pool = svc._create_worker_pool(1)
    assert pool is not None
    try:
        spec_origin = pool.submit(_find_backend_origin).result(timeout=60)
    finally:
        pool.shutdown(wait=True, cancel_futures=True)

    assert spec_origin is not None
    assert importlib.util.find_spec("backend") is not None


def _find_backend_origin() -> str | None:
    """子プロセス側で `backend` パッケージを解決できるかを返す（pickle 可能なトップレベル関数）."""
    import importlib.util

    spec = importlib.util.find_spec("backend")
    return None if spec is None else spec.origin


async def test_run_daily_training_batch_processes_in_windows_of_max_parallel_workers(
    migrated_db: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`max_parallel_workers` ぶんずつ「running」イベントがまとめて発火するウィンドウ処理を確認する.

    5銘柄・max_parallel_workers=2 なら、ウィンドウは [2銘柄, 2銘柄, 1銘柄] の3回に分かれ、
    各ウィンドウ内では running イベント群がまとめて先に発火してから completed イベント群が
    続く（ウィンドウをまたいだ running/completed の入れ替わりは起きない）。
    """
    tickers = ["1111", "2222", "3333", "4444", "5555"]
    universe = [TickerInfo(code=c, name=c, sector=None) for c in tickers]
    monkeypatch.setattr(svc.training_target_service, "resolve_training_universe", _async_return(universe))
    monkeypatch.setattr(svc, "fetch_training_ohlcv", _fake_fetch_training_ohlcv)
    monkeypatch.setattr(svc, "_daily_ticker_limit", lambda model_type: 10)
    await training_target_service.update_settings(max_parallel_workers=2)

    events: list[svc.TrainingProgressEvent] = []
    summary = await svc.run_daily_training_batch("xgboost", on_progress=events.append)

    assert summary.trained_this_call == 5
    statuses = [(e.ticker, e.status) for e in events]
    assert statuses == [
        ("1111", "running"),
        ("2222", "running"),
        ("1111", "completed"),
        ("2222", "completed"),
        ("3333", "running"),
        ("4444", "running"),
        ("3333", "completed"),
        ("4444", "completed"),
        ("5555", "running"),
        ("5555", "completed"),
    ]


async def test_run_daily_training_batch_uses_default_four_workers_when_unset(
    migrated_db: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """学習対象設定が未保存でも並列数上限は既定の4になる（学習対象設定の後方互換フォールバック）."""
    tickers = ["1111", "2222", "3333"]
    universe = [TickerInfo(code=c, name=c, sector=None) for c in tickers]
    monkeypatch.setattr(svc.training_target_service, "resolve_training_universe", _async_return(universe))
    monkeypatch.setattr(svc, "fetch_training_ohlcv", _fake_fetch_training_ohlcv)
    monkeypatch.setattr(svc, "_daily_ticker_limit", lambda model_type: 10)

    events: list[svc.TrainingProgressEvent] = []
    await svc.run_daily_training_batch("xgboost", on_progress=events.append)

    running_tickers = [e.ticker for e in events if e.status == "running"]
    # 3銘柄が既定の並列数上限（4）に収まるため、1ウィンドウで全銘柄の running が先に揃う。
    assert running_tickers == tickers
