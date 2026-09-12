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
- ユニバースは東証全銘柄（`data_fetcher._get_ticker_master()`、ユーザー確認済み仕様。
  Market Lens 同様）。

「1呼び出し（Celery beat の1firing）あたりの時間予算・1銘柄あたりタイムアウトを守りつつ、
未学習優先→最も学習が古い順に候補を選び、当日上限まで学習する」という Market Lens の設計を
そのまま踏襲する。新規の進捗カーソルは持たず、毎回以下を DB から読み直すことで
「続きから再開」する:
- 今日そのモデルタイプで試行済み（成功/失敗いずれも）の銘柄集合（`training_batch_runs`）
- 銘柄ごとの最新学習日時（`model_registry`）
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from typing import Final, Literal

from backend.config import settings
from backend.services.data.data_fetcher import _get_ticker_master
from backend.services.db import model_registry_db, training_batch_db
from backend.services.jst_time import today_jst
from backend.services.learning.dl.lstm import LSTMPredictor
from backend.services.learning.dl.transformer import TransformerPredictor
from backend.services.learning.per_ticker_predictor import RandomForestPredictor, XGBoostPredictor
from backend.services.learning.predictor_protocol import PredictorProtocol
from backend.services.learning.training_data_source import fetch_training_ohlcv

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

    for ticker in candidates:
        if len(attempted_today) + trained + failed >= limit:
            break
        if time.monotonic() - start >= budget:
            break

        if on_progress is not None:
            on_progress(
                TrainingProgressEvent(ticker=ticker, processed=trained + failed, total=planned_total, status="running")
            )

        version = f"{_BATCH_VERSION_PREFIX}{uuid.uuid4()}"
        try:
            new_metrics, df, data_source = await asyncio.wait_for(
                _train_and_register(ticker, model_type, version), timeout=timeout
            )
        except TimeoutError:
            logger.warning("日次学習バッチ[%s]: %s の学習が%.0f秒でタイムアウトしました", model_type, ticker, timeout)
            await training_batch_db.insert_training_batch_run(
                run_date=run_date,
                ticker=ticker,
                model_type=model_type,
                status="failed",
                error=f"タイムアウト（{timeout:.0f}秒）",
            )
            failed += 1
            if on_progress is not None:
                on_progress(
                    TrainingProgressEvent(
                        ticker=ticker, processed=trained + failed, total=planned_total, status="failed"
                    )
                )
            continue
        except Exception as exc:  # noqa: BLE001 - 1銘柄の失敗で全体を止めない
            logger.warning("日次学習バッチ[%s]: %s の学習に失敗しました: %s", model_type, ticker, exc, exc_info=True)
            await training_batch_db.insert_training_batch_run(
                run_date=run_date, ticker=ticker, model_type=model_type, status="failed", error=str(exc)
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
            data_source=data_source,
        )
        trained += 1
        promoted = await _apply_quality_gate(ticker, model_type, version, new_metrics, df)
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
                    data_source=data_source,
                )
            )

    total_attempted_today = len(attempted_today) + trained + failed
    return TrainingBatchSummary(
        model_type=model_type,
        attempted_today=total_attempted_today,
        trained_this_call=trained,
        failed_this_call=failed,
        quota_reached=total_attempted_today >= limit,
        activated_this_call=activated,
    )


async def _train_and_register(
    ticker: str, model_type: str, version: str
) -> tuple[dict[str, float | str | int | bool], object, str]:
    """1銘柄を学習し、`model_registry` へ登録する（champion 化は品質ゲートに委ねる）.

    戻り値の第2要素（学習に使った OHLCV データフレーム）は、品質ゲートが既存 champion を
    同じ検証窓で再評価する際、追加のネットワーク取得なしに再利用するために返す
    （`get_stock_data` は TTL キャッシュ済みのため実害はほぼ無いが、素朴に再利用する）。
    第3要素は実際に採用したデータソース（🆕 P17、"yfinance"/"jquants"）。

    データ取得は yfinance を優先し、履歴が不十分な場合は J-Quants にフォールバックする
    （🆕 P14、`training_data_source.fetch_training_ohlcv` 参照）。
    """
    df, data_source = await fetch_training_ohlcv(ticker, period=_TRAINING_PERIOD)
    if df.empty:
        raise ValueError(f"株価データが取得できません: {ticker}")

    predictor = get_predictor(model_type)
    metrics = await asyncio.to_thread(predictor.train, df, {}, forecast_horizon=FORECAST_HORIZON_DAYS)
    artifact_path = await asyncio.to_thread(predictor.save, version)

    await model_registry_db.upsert_model(
        version=version,
        model_type=model_type,
        ticker=ticker,
        objective="regression",
        artifact_path=artifact_path,
        val_metrics=metrics,
        feature_list=[],
        trained_at=None,
    )
    return metrics, df, data_source


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


async def _reevaluate_existing_on_window(
    model_type: str, existing_row: dict[str, object], new_metrics: dict[str, float | str | int | bool], df: object
) -> float | None:
    """既存 champion を新モデルと同じ eval 窓（eval_start〜eval_end）で再評価する.

    日次バッチは実行日が1日ずれるだけで学習・検証ウィンドウ全体もずれるため、
    「記録済みの既存RMSE」と「新モデルのRMSE」を単純比較すると、たまたま静かな検証窓を
    引いた側が有利になる。既存 champion を新モデルの評価窓に合わせて再評価し、
    フェアな比較にする。再評価できない場合は None を返し、呼び出し元は記録済み値へ
    フォールバックする（安全側 — 再評価できないことは品質ゲートを無効化する理由にしない）。
    """
    eval_start = new_metrics.get("eval_start")
    eval_end = new_metrics.get("eval_end")
    if not isinstance(eval_start, str) or not isinstance(eval_end, str):
        return None

    artifact_path = existing_row.get("artifact_path")
    if not artifact_path:
        return None

    try:
        predictor = get_predictor(model_type)
        await asyncio.to_thread(predictor.load, str(artifact_path))
        rewindow_metrics = await asyncio.to_thread(predictor.evaluate_on, df, eval_start, eval_end)
        return rewindow_metrics.get("rmse")
    except Exception:
        logger.debug("既存 champion の再評価に失敗しました。記録済みRMSEにフォールバックします。", exc_info=True)
        return None


async def _apply_quality_gate(
    ticker: str, model_type: str, version: str, new_metrics: dict[str, float | str | int | bool], df: object
) -> bool:
    """新モデルが既存 champion より悪化していないか検証し、悪化していなければ champion にする.

    - ナイーブ予測（変化率0）より悪いモデル（skill<=0）は既存 champion の有無に関わらず
      無条件で却下する（Market Lens のオフライン検証で active XGBoost の74%がナイーブ予測
      以下と判明したことを受けた対策、`per_ticker_predictor._calculate_metrics` docstring 参照）。
    - この銘柄・モデルタイプで champion が未設定（初めての学習）なら、比較のしようがないため
      無条件で champion にする。
    - champion が既にある場合、新モデルの RMSE が（同じ窓で再評価した）既存以下なら champion
      を差し替える。

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
    existing_version = await model_registry_db.get_champion(lane)
    if existing_version is None:
        await model_registry_db.set_champion(lane, version, promoted_by="quality_gate")
        return True

    new_rmse = new_metrics.get("rmse")
    if not (isinstance(new_rmse, int | float) and not isinstance(new_rmse, bool) and new_rmse >= 0):
        logger.info("日次学習バッチ[%s]: %s は新モデルのRMSEが取得できず却下されました。", model_type, ticker)
        return False

    existing_row = await model_registry_db.get_model(existing_version)
    if existing_row is None:
        # 既存 champion のレジストリ行が見つからない（データ不整合）場合は安全側で採用する
        await model_registry_db.set_champion(lane, version, promoted_by="quality_gate")
        return True

    comparison_rmse = await _reevaluate_existing_on_window(model_type, existing_row, new_metrics, df)
    if comparison_rmse is None:
        comparison_rmse = _rmse_from_val_metrics(existing_row)

    if comparison_rmse is None or new_rmse <= comparison_rmse:
        await model_registry_db.set_champion(lane, version, promoted_by="quality_gate")
        return True

    logger.info(
        "日次学習バッチ[%s]: %s は品質ゲートで却下されました（新RMSE=%.4f, 比較対象RMSE=%.4f）。"
        "既存 champion を維持します。",
        model_type,
        ticker,
        new_rmse,
        comparison_rmse,
    )
    return False


async def _select_candidates(attempted_today: set[str], model_type: str) -> list[str]:
    """学習候補銘柄を優先順位（未学習 → 学習が最も古い順）でソートして返す.

    当日そのモデルタイプで試行済み（成功/失敗問わず）の銘柄は除外する
    （失敗銘柄を同日中に繰り返し試行してループしないため。翌日、改めて最優先候補として再挑戦される）。
    """
    universe = await _get_ticker_master()
    latest_trained = await training_batch_db.get_latest_trained_at_by_ticker(model_type)

    remaining = [t.code for t in universe if t.code not in attempted_today]
    # 未学習（latest_trainedに無い）銘柄を最優先（Falseはtrue未満なので先頭に来る）、
    # 学習済み銘柄同士は trained_at 昇順（最も古い＝最も長く再学習されていない銘柄を優先）。
    remaining.sort(key=lambda code: (code in latest_trained, latest_trained.get(code, "")))
    return remaining
