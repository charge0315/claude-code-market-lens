"""銘柄別モデル（P9）の日次学習バッチのコアロジック（モデルタイプ別）.

Market Lens `backend/services/training_batch_service.py` から移植、変更点:
- `database.activate_model`（per-ticker `is_active` フラグ）は Alpha Forge に存在しないため、
  品質ゲート合格時は `model_registry_db.set_champion(lane=f"{model_type}:{ticker}", version,
  promoted_by="quality_gate")` で `model_champions` の該当行を差し替える。既存の
  `model_champions`/`model_promotions`（ml_pool/mid_term/short_term レーンの人手承認ゲート、
  `services/registry/promotion.py`）とは別格の**自動承認ガバナンス**として意図的に区別する
  （`plans/04_タスクリスト.md` P9。CLAUDE.md の「モデル昇格は人手承認のみ」原則に対する、
  ユーザー確認済みの明示的なスコープ限定の例外 — 銘柄別モデルは1系統あたり数千件に上り、
  1件ずつの人手承認は運用不可能なため）。`model_promotions`（人手承認履歴）には書き込まない。
- 「最新モデルが手動学習/チューニングで作られた銘柄は保護対象として除外する」ロジックは
  Alpha Forge に手動学習 UI が無いため移植しない（全銘柄が常にバッチ対象）。
- 分類器（objective="classification"）の出荷ゲートは無い。銘柄別4モデルは回帰専用
  （`per_ticker_predictor.py`/`dl/base.py` 参照）。
- ユニバースは東証全銘柄固定だったが、🆕 学習対象設定（`training_target_service.py`）により
  ポートフォリオ銘柄/ピック銘柄/カスタムリストへ絞り込めるようにした（既定は従来通り全銘柄）。

「1呼び出し（Celery beat の1firing）あたりの時間予算・1銘柄あたりタイムアウトを守りつつ、
未学習優先→最も学習が古い順に候補を選び、当日上限まで学習する」という Market Lens の設計を
そのまま踏襲する。新規の進捗カーソルは持たず、毎回以下を DB から読み直すことで
「続きから再開」する:
- 今日そのモデルタイプで試行済み（成功/失敗いずれも）の銘柄集合（`training_batch_runs`）
- 銘柄ごとの最新学習日時（`model_registry`）
"""

from __future__ import annotations

import asyncio
import functools
import json
import logging
import sys
import time
import uuid
from collections.abc import Callable
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Final, Literal

from backend.config import settings
from backend.services.db import model_registry_db, training_batch_db
from backend.services.jst_time import today_jst
from backend.services.learning import training_target_service
from backend.services.learning.dl.lstm import LSTMPredictor
from backend.services.learning.dl.transformer import TransformerPredictor
from backend.services.learning.per_ticker_predictor import RandomForestPredictor, XGBoostPredictor
from backend.services.learning.predictor_protocol import PredictorProtocol
from backend.services.learning.training_data_source import fetch_training_ohlcv
from backend.services.learning.training_worker import TrainWorkerResult, train_ticker_in_subprocess

logger = logging.getLogger(__name__)

ModelType = Literal["xgboost", "random_forest", "lstm", "transformer"]
PER_TICKER_MODEL_TYPES: Final[tuple[ModelType, ...]] = ("xgboost", "random_forest", "lstm", "transformer")

# torch ベースで学習が重く、立会時間ゲート・別予算を使うモデルタイプ。
_DL_MODEL_TYPES: Final[frozenset[str]] = frozenset({"lstm", "transformer"})

# 1回の呼び出し（Celery beatの1firing分）で学習に費やしてよい上限時間。
# beatは次のfiringが来る前に余裕を持って制御を返せるよう、発火間隔よりやや短い値にする。
_MAX_BATCH_DURATION_SECONDS: Final[float] = 240.0  # xgboost / random_forest（5分間隔）
_DL_MAX_BATCH_DURATION_SECONDS: Final[float] = 600.0  # lstm / transformer（60分間隔なので長く取れる）

# 1銘柄あたりの学習タイムアウト。_max_batch_duration のチェックはループの各イテレーション
# 「間」でしか行われないため、1銘柄の学習/取得がハングするとソフトな時間予算を大きく超過する。
_PER_TICKER_TIMEOUT_SECONDS: Final[float] = 60.0  # xgboost / random_forest
_DL_PER_TICKER_TIMEOUT_SECONDS: Final[float] = 300.0  # lstm / transformer（torch 学習 + early stopping）

# バッチが学習したモデルのversion接頭辞。
_BATCH_VERSION_PREFIX: Final[str] = "batch-"

# 学習データの取得期間・予測ホライズン（Market Lens のデフォルトを踏襲）。
_TRAINING_PERIOD: Final[str] = "5y"
FORECAST_HORIZON_DAYS: Final[int] = 5

# 🆕 P14: 手動トリガー（モデルラボの「今すぐ学習」ボタン、P13h でバックグラウンドタスク化
# 済み）専用の上限。`training_xgboost_daily_limit` 等（200/200/40/40）は celery-beat の
# 1firing予算に合わせた値であり、東証全銘柄（~4000銘柄）には遠く及ばない人為的な上限
# だったため、手動トリガーはこの上限を使わず「いけるところまでいく」（ユーザー確認済み）。
# 件数上限は東証全銘柄に十分な安全マージンを持たせた値、時間予算は「暴走を止める安全網」
# であり目標ではない（既存の 240:600 という classical:DL の比率を踏襲して倍率を保つ）。
# celery-beat の自動定期実行（`tasks.py`）はこれらを使わず、既存の
# _daily_ticker_limit/_max_batch_duration のまま変更しない。
_MANUAL_FULL_RUN_DAILY_LIMIT: Final[int] = 10_000
_MANUAL_FULL_RUN_DURATION_SECONDS: Final[float] = 6 * 3600.0  # xgboost / random_forest
_MANUAL_FULL_RUN_DL_DURATION_SECONDS: Final[float] = 12 * 3600.0  # lstm / transformer


def get_predictor(model_type: str) -> PredictorProtocol:
    """モデルタイプ文字列から対応する predictor インスタンスを返す."""
    if model_type == "xgboost":
        return XGBoostPredictor()
    if model_type == "random_forest":
        return RandomForestPredictor()
    if model_type == "lstm":
        return LSTMPredictor()
    if model_type == "transformer":
        return TransformerPredictor()
    raise ValueError(f"Unsupported model type: {model_type}")


def _daily_ticker_limit(model_type: str) -> int:
    """モデルタイプ別の当日学習上限銘柄数（モジュール import 時ではなく実行時に settings を読む）."""
    if model_type == "random_forest":
        return settings.training_random_forest_daily_limit
    if model_type == "lstm":
        return settings.training_lstm_daily_limit
    if model_type == "transformer":
        return settings.training_transformer_daily_limit
    return settings.training_xgboost_daily_limit


def _per_ticker_timeout(model_type: str) -> float:
    return _DL_PER_TICKER_TIMEOUT_SECONDS if model_type in _DL_MODEL_TYPES else _PER_TICKER_TIMEOUT_SECONDS


def _max_batch_duration(model_type: str) -> float:
    return _DL_MAX_BATCH_DURATION_SECONDS if model_type in _DL_MODEL_TYPES else _MAX_BATCH_DURATION_SECONDS


def manual_full_run_overrides(model_type: str) -> tuple[int, float]:
    """手動トリガー（「今すぐ学習」ボタン）向けの (daily_limit, max_duration) を返す（🆕 P14）.

    `routers/registry.py` の手動トリガーが `run_daily_training_batch` を呼ぶ際に使う。
    celery-beat の自動定期実行はこれを使わず、既存の `_daily_ticker_limit`/
    `_max_batch_duration`（settings 由来の件数上限・240秒/600秒予算）のまま変更しない。
    """
    if model_type in _DL_MODEL_TYPES:
        return _MANUAL_FULL_RUN_DAILY_LIMIT, _MANUAL_FULL_RUN_DL_DURATION_SECONDS
    return _MANUAL_FULL_RUN_DAILY_LIMIT, _MANUAL_FULL_RUN_DURATION_SECONDS


def _lane(model_type: str, ticker: str) -> str:
    """銘柄別モデルの champion レーン名（`model_champions.lane`、String(32) に収まる）."""
    return f"{model_type}:{ticker}"


@dataclass(frozen=True)
class TrainingProgressEvent:
    """1銘柄の学習開始/終了時に `on_progress` へ渡す進捗イベント（🆕 P17）.

    モデルラボの「学習の状況」表示（処理中の銘柄・残り推定時間・精度スコア既存比）を
    ポーリング可能にするため、`run_daily_training_batch` 呼び出し元（`routers/registry.py`）
    がこのイベントを受け取ってインメモリの進捗状態を更新する。
    """

    ticker: str
    processed: int
    total: int
    status: Literal["running", "completed", "failed"]
    activated: bool = False
    data_source: str | None = None


class TrainingBatchSummary:
    """1回の呼び出し分の実行結果サマリ（Celery タスクの戻り値用）."""

    def __init__(
        self,
        *,
        model_type: str,
        attempted_today: int,
        trained_this_call: int,
        failed_this_call: int,
        quota_reached: bool,
        activated_this_call: int = 0,
    ) -> None:
        self.model_type = model_type
        self.attempted_today = attempted_today
        self.trained_this_call = trained_this_call
        self.failed_this_call = failed_this_call
        self.quota_reached = quota_reached
        # 学習に成功した件数のうち、品質ゲートを通過して実際に champion 化された件数。
        self.activated_this_call = activated_this_call

    def to_dict(self) -> dict[str, object]:
        return {
            "model_type": self.model_type,
            "attempted_today": self.attempted_today,
            "trained_this_call": self.trained_this_call,
            "failed_this_call": self.failed_this_call,
            "quota_reached": self.quota_reached,
            "activated_this_call": self.activated_this_call,
        }


async def run_daily_training_batch(
    model_type: ModelType,
    *,
    daily_limit_override: int | None = None,
    max_duration_override: float | None = None,
    on_progress: Callable[[TrainingProgressEvent], None] | None = None,
) -> TrainingBatchSummary:
    """当日の学習上限に達するまで、未学習/学習が最も古い銘柄から順に当該モデルタイプで学習する.

    `daily_limit_override`/`max_duration_override` は手動トリガー（🆕 P14、
    `manual_full_run_overrides` 参照）専用。省略時（celery-beat の自動定期実行）は
    既存の `_daily_ticker_limit`/`_max_batch_duration`（settings 由来）のまま変更しない。

    `on_progress`（🆕 P17）は各銘柄の学習開始/終了時に呼ばれるコールバック。
    呼び出し元（`routers/registry.py`）がこれを使ってインメモリの進捗状態
    （処理中の銘柄・残り推定時間・既存比等）を更新し、`GET /training/status` で
    ポーリング可能にする。celery-beat 経路では渡されず、動作に影響しない。

    🆕 学習対象設定の並列数上限（既定4）ぶんずつ「ウィンドウ」単位で並列学習する
    （`training_target_service.get_settings().max_parallel_workers`）。ウィンドウ内の
    データ取得（I/O）は `asyncio.gather` で並列化し、CPU バウンドな学習・保存は
    `_create_worker_pool` が返すプロセスプールへ委譲する（`training_worker.py` 参照）。
    並列数の変更は次回のバッチ呼び出しから反映される（実行中バッチはそのまま完走する）。
    """
    run_date = today_jst()
    limit = daily_limit_override if daily_limit_override is not None else _daily_ticker_limit(model_type)
    budget = max_duration_override if max_duration_override is not None else _max_batch_duration(model_type)
    timeout = _per_ticker_timeout(model_type)

    attempted_today = await training_batch_db.get_attempted_tickers(run_date, model_type)
    if len(attempted_today) >= limit:
        return TrainingBatchSummary(
            model_type=model_type,
            attempted_today=len(attempted_today),
            trained_this_call=0,
            failed_this_call=0,
            quota_reached=True,
        )

    candidates = await _select_candidates(attempted_today, model_type)
    # 進捗表示用の「今回の予定件数」。実際にはさらに時間予算で打ち切られうる上限見積り。
    planned_total = min(len(candidates), limit - len(attempted_today))

    trained = 0
    failed = 0
    activated = 0
    start = time.monotonic()

    max_parallel_workers = (await training_target_service.get_settings()).max_parallel_workers
    pool = _create_worker_pool(max_parallel_workers)
    try:
        remaining = list(candidates)
        while remaining:
            already_processed = len(attempted_today) + trained + failed
            if already_processed >= limit:
                break
            if time.monotonic() - start >= budget:
                break

            window = remaining[:max_parallel_workers]
            remaining = remaining[max_parallel_workers:]
            window = window[: limit - already_processed]
            if not window:
                break

            for ticker in window:
                if on_progress is not None:
                    on_progress(
                        TrainingProgressEvent(
                            ticker=ticker, processed=trained + failed, total=planned_total, status="running"
                        )
                    )

            versions = {ticker: f"{_BATCH_VERSION_PREFIX}{uuid.uuid4()}" for ticker in window}
            outcomes = await asyncio.gather(
                *(
                    asyncio.wait_for(_process_ticker(ticker, model_type, versions[ticker], pool), timeout=timeout)
                    for ticker in window
                ),
                return_exceptions=True,
            )

            for ticker, outcome in zip(window, outcomes, strict=True):
                if isinstance(outcome, BaseException):
                    if isinstance(outcome, TimeoutError):
                        logger.warning(
                            "日次学習バッチ[%s]: %s の学習が%.0f秒でタイムアウトしました", model_type, ticker, timeout
                        )
                        error = f"タイムアウト（{timeout:.0f}秒）"
                    else:
                        logger.warning(
                            "日次学習バッチ[%s]: %s の学習に失敗しました: %s",
                            model_type,
                            ticker,
                            outcome,
                            exc_info=outcome,
                        )
                        error = str(outcome)
                    await training_batch_db.insert_training_batch_run(
                        run_date=run_date, ticker=ticker, model_type=model_type, status="failed", error=error
                    )
                    failed += 1
                    if on_progress is not None:
                        on_progress(
                            TrainingProgressEvent(
                                ticker=ticker, processed=trained + failed, total=planned_total, status="failed"
                            )
                        )
                    continue

                await training_batch_db.insert_training_batch_run(
                    run_date=run_date,
                    ticker=ticker,
                    model_type=model_type,
                    status="completed",
                    error=None,
                    data_source=outcome.data_source,
                )
                trained += 1
                promoted = await _apply_quality_gate_from_worker_result(
                    ticker,
                    model_type,
                    versions[ticker],
                    outcome.worker_result.metrics,
                    existing_version=outcome.existing_version,
                    existing_row=outcome.existing_row,
                    comparison_rmse=outcome.worker_result.comparison_rmse,
                )
                if promoted:
                    activated += 1
                if on_progress is not None:
                    on_progress(
                        TrainingProgressEvent(
                            ticker=ticker,
                            processed=trained + failed,
                            total=planned_total,
                            status="completed",
                            activated=promoted,
                            data_source=outcome.data_source,
                        )
                    )
    finally:
        if pool is not None:
            pool.shutdown(wait=True)

    total_attempted_today = len(attempted_today) + trained + failed
    return TrainingBatchSummary(
        model_type=model_type,
        attempted_today=total_attempted_today,
        trained_this_call=trained,
        failed_this_call=failed,
        quota_reached=total_attempted_today >= limit,
        activated_this_call=activated,
    )


# backend/services/learning/per_ticker_training_service.py → プロジェクトルートまで4階層上。
_PROJECT_ROOT: Final[Path] = Path(__file__).resolve().parents[3]


def _ensure_project_root_on_sys_path() -> None:
    """`ProcessPoolExecutor` が spawn する子プロセスへ `backend` パッケージを確実に見せる.

    `celery.exe -A backend.celery_app` は app の import 中だけ `cwd_in_path()` で cwd を
    `sys.path` に足し、import 後に取り除く。そのため親プロセスは `backend` を import 済みでも
    `sys.path` にプロジェクトルートが残らない。spawn の子プロセスは起動直後に `sys.path` を
    親のコピーで丸ごと上書きする（`multiprocessing.spawn.prepare`）ので、子は
    `ModuleNotFoundError: No module named 'backend'` で即死し、プールが壊れて後続全銘柄が
    失敗する（2026-09-20 発生）。当初は `PYTHONPATH` 環境変数で対策したが、この上書きで
    消されて効いておらず 2026-09-23 に全件失敗が再発した。親の `sys.path` 自体へ入れれば
    子へコピーされる。
    """
    root = str(_PROJECT_ROOT)
    if root not in sys.path:
        sys.path.insert(0, root)


def _create_worker_pool(max_workers: int) -> ProcessPoolExecutor | None:
    """学習バッチ用のプロセスプールを生成する（テストから差し替え可能にするための間接層）.

    `None` を返すと `loop.run_in_executor` は既定のスレッドプール（イベントループ共有、
    同一プロセス内）を使う。テストでは autouse fixture（`conftest.py` の
    `_use_thread_pool_for_training_batch`）がこの関数を `None` を返すよう差し替える —
    `ProcessPoolExecutor` の `spawn` は子プロセスを新規 Python インタプリタとして起動する
    ため、monkeypatch によるモデル保存先の隔離（`_isolated_per_ticker_model_dir` 等）が
    子プロセスへ引き継がれず、テストの独立性が壊れてしまうため。
    """
    _ensure_project_root_on_sys_path()
    return ProcessPoolExecutor(max_workers=max_workers)


@dataclass(frozen=True)
class _TickerTrainOutcome:
    """1銘柄ぶんの学習結果（親プロセス側で品質ゲート判定・DB書き込みに使う）."""

    worker_result: TrainWorkerResult
    data_source: str
    existing_version: str | None
    existing_row: dict[str, object] | None


async def _process_ticker(
    ticker: str, model_type: str, version: str, pool: ProcessPoolExecutor | None
) -> _TickerTrainOutcome:
    """1銘柄のデータ取得（親プロセス I/O）→ 学習（子プロセス/スレッド CPU）→ 登録を行う.

    データ取得は yfinance を優先し、履歴が不十分な場合は J-Quants にフォールバックする
    （🆕 P14、`training_data_source.fetch_training_ohlcv` 参照）。既存 champion の
    アーティファクトパスは学習前にここ（親プロセス）で DB から解決し、子プロセスへ渡す
    （子プロセスは DB に一切アクセスしない設計、`training_worker.py` docstring 参照）。
    """
    df, data_source = await fetch_training_ohlcv(ticker, period=_TRAINING_PERIOD)
    if df.empty:
        raise ValueError(f"株価データが取得できません: {ticker}")

    lane = _lane(model_type, ticker)
    existing_version = await model_registry_db.get_champion(lane)
    existing_row = await model_registry_db.get_model(existing_version) if existing_version is not None else None
    existing_artifact_path = existing_row.get("artifact_path") if existing_row is not None else None

    loop = asyncio.get_running_loop()
    worker = functools.partial(
        train_ticker_in_subprocess,
        ticker=ticker,
        model_type=model_type,
        version=version,
        df=df,
        forecast_horizon=FORECAST_HORIZON_DAYS,
        existing_artifact_path=str(existing_artifact_path) if existing_artifact_path else None,
    )
    result = await loop.run_in_executor(pool, worker)

    await model_registry_db.upsert_model(
        version=version,
        model_type=model_type,
        ticker=ticker,
        objective="regression",
        artifact_path=result.artifact_path,
        val_metrics=result.metrics,
        feature_list=[],
        trained_at=None,
    )
    return _TickerTrainOutcome(
        worker_result=result, data_source=data_source, existing_version=existing_version, existing_row=existing_row
    )


def _rmse_from_val_metrics(row: dict[str, object]) -> float | None:
    """`model_registry.val_metrics`（JSON文字列）からrmseを取り出す。取得できなければNone."""
    raw = row.get("val_metrics")
    try:
        metrics = json.loads(raw) if isinstance(raw, str) else (raw or {})
    except json.JSONDecodeError:
        return None
    if not isinstance(metrics, dict):
        return None
    rmse = metrics.get("rmse")
    return float(rmse) if isinstance(rmse, int | float) and not isinstance(rmse, bool) and rmse >= 0 else None


async def _apply_quality_gate_from_worker_result(
    ticker: str,
    model_type: str,
    version: str,
    new_metrics: dict[str, float | str | int | bool],
    *,
    existing_version: str | None,
    existing_row: dict[str, object] | None,
    comparison_rmse: float | None,
) -> bool:
    """新モデルが既存 champion より悪化していないか検証し、悪化していなければ champion にする.

    既存 champion の同一窓再評価（CPU バウンド）は `train_ticker_in_subprocess`
    （子プロセス側、🆕）で完了済みのため、ここでは比較判定と DB 書き込みのみを行う
    （旧 `_apply_quality_gate` の DB 相当部分。判定ロジック自体は変更していない）。

    - ナイーブ予測（変化率0）より悪いモデル（skill<=0）は既存 champion の有無に関わらず
      無条件で却下する（Market Lens のオフライン検証で active XGBoost の74%がナイーブ予測
      以下と判明したことを受けた対策、`per_ticker_predictor._calculate_metrics` docstring 参照）。
    - この銘柄・モデルタイプで champion が未設定（初めての学習）なら、比較のしようがないため
      無条件で champion にする。
    - champion が既にある場合、新モデルの RMSE が（同じ窓で再評価した）既存以下なら champion
      を差し替える。`comparison_rmse` が None（子プロセスでの再評価に失敗）の場合は記録済み
      RMSE（`_rmse_from_val_metrics`）へフォールバックする。

    Returns
    -------
    bool
        実際に `model_champions` を差し替えた場合 True。
    """
    new_skill = new_metrics.get("skill")
    if isinstance(new_skill, int | float) and not isinstance(new_skill, bool) and new_skill <= 0.0:
        logger.info(
            "日次学習バッチ[%s]: %s は品質ゲートで却下されました（skill=%.3f <= 0、"
            "ナイーブ予測（変化率0）以下のため不採用）。",
            model_type,
            ticker,
            new_skill,
        )
        return False

    lane = _lane(model_type, ticker)
    if existing_version is None:
        await model_registry_db.set_champion(lane, version, promoted_by="quality_gate")
        return True

    new_rmse = new_metrics.get("rmse")
    if not (isinstance(new_rmse, int | float) and not isinstance(new_rmse, bool) and new_rmse >= 0):
        logger.info("日次学習バッチ[%s]: %s は新モデルのRMSEが取得できず却下されました。", model_type, ticker)
        return False

    if existing_row is None:
        # 既存 champion のレジストリ行が見つからない（データ不整合）場合は安全側で採用する
        await model_registry_db.set_champion(lane, version, promoted_by="quality_gate")
        return True

    resolved_comparison_rmse = comparison_rmse if comparison_rmse is not None else _rmse_from_val_metrics(existing_row)

    if resolved_comparison_rmse is None or new_rmse <= resolved_comparison_rmse:
        await model_registry_db.set_champion(lane, version, promoted_by="quality_gate")
        return True

    logger.info(
        "日次学習バッチ[%s]: %s は品質ゲートで却下されました（新RMSE=%.4f, 比較対象RMSE=%.4f）。"
        "既存 champion を維持します。",
        model_type,
        ticker,
        new_rmse,
        resolved_comparison_rmse,
    )
    return False


async def _select_candidates(attempted_today: set[str], model_type: str) -> list[str]:
    """学習候補銘柄を優先順位（未学習 → 学習が最も古い順）でソートして返す.

    当日そのモデルタイプで試行済み（成功/失敗問わず）の銘柄は除外する
    （失敗銘柄を同日中に繰り返し試行してループしないため。翌日、改めて最優先候補として再挑戦される）。

    ユニバースは `training_target_service.resolve_training_universe()`（🆕 学習対象設定、
    既定は従来通り東証全銘柄）。`custom` モードで新規追加された銘柄は、学習対象への追加日時が
    最終学習日時より後なら「未学習」扱いに昇格させ最優先候補にする（要件6の差分学習）。

    「最後に試した日時」は成功（`model_registry.trained_at`）と失敗（`training_batch_runs`）の
    新しい方を使う。成功日時だけだと、データ不足で恒常的に失敗する銘柄が永久に「未学習」扱いで
    毎日先頭に来て日次枠を使い切り、学習済み銘柄の再学習が止まる（2026-09-21〜24 に発生）。
    失敗銘柄も一巡に1回は再挑戦されるため、データが揃えばいずれ学習される。
    """
    universe = await training_target_service.resolve_training_universe()
    latest_trained = await training_batch_db.get_latest_trained_at_by_ticker(model_type)
    latest_failed = await training_batch_db.get_latest_failed_at_by_ticker(model_type)
    priority_override = await training_target_service.get_priority_override_map()

    remaining = [t.code for t in universe if t.code not in attempted_today]

    def sort_key(code: str) -> tuple[bool, str]:
        # どちらも ISO8601（+09:00）文字列のため、文字列比較で時系列順になる
        attempts = [ts for ts in (latest_trained.get(code), latest_failed.get(code)) if ts is not None]
        last_attempt = max(attempts) if attempts else None
        added_at = priority_override.get(code)
        if last_attempt is not None and added_at is not None and added_at > last_attempt:
            last_attempt = None
        # 一度も試行していない銘柄を最優先（Falseはtrue未満なので先頭に来る）、
        # 試行済み銘柄同士は last_attempt 昇順（最も長く試していない銘柄を優先）。
        return (last_attempt is not None, last_attempt or "")

    remaining.sort(key=sort_key)
    return remaining
