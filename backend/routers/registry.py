"""モデルレジストリ関連 API（champion/challenger・昇格ゲート・PSI ドリフト）.

`plans/03_システム設計` §2.4。昇格は**人手承認 API 経由でのみ**行う
（`POST /promotions/{id}/apply`。自動昇格は既定 OFF、CLAUDE.md）。
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Literal

from fastapi import APIRouter, Query
from pydantic import BaseModel

from backend.models.common import ApiResponse
from backend.models.registry import (
    ModelCoverage,
    PitCoverageStatus,
    QualityDistribution,
    SourceAblationEntry,
    TrainingTargetSettingsResponse,
    TrainingTargetSettingsUpdateRequest,
    TrainingTargetTickerEntry,
    TrainingTargetTickersUpdateRequest,
    TrainingTrendPoint,
)
from backend.services.data.data_fetcher import _get_ticker_master
from backend.services.data.ticker_universe_service import TickerUniverseEntry, TickerUniverseSort, list_ticker_universe
from backend.services.db import training_target_db
from backend.services.db.drift_db import list_drift_snapshots
from backend.services.db.model_registry_db import list_champions, list_promotions
from backend.services.db.source_ablation_db import list_ablations
from backend.services.db.training_batch_db import get_attempted_tickers
from backend.services.jst_time import today_jst
from backend.services.learning import training_target_service
from backend.services.learning.per_ticker_training_service import (
    ModelType,
    TrainingProgressEvent,
    manual_full_run_overrides,
    run_daily_training_batch,
)
from backend.services.learning.pool_model import POOL_LANE
from backend.services.registry import model_stats_service, pit_coverage_service
from backend.services.registry.promotion import apply_promotion, evaluate_ml_pool_promotion, evaluate_promotion

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/registry", tags=["registry"])

# 銘柄別モデルの日次学習バッチ（🔧 P13h）: モデルタイプごとに数十秒〜10分かかりうるため、
# HTTP リクエスト内で同期 await すると（Next.js の rewrite プロキシ等、経路上のどこかの
# タイムアウトに引っかかり）ブラウザ側には失敗と映る一方、バックエンド側はそのまま処理を
# 続行してしまう（実際に学習・champion 化は成立するのに UI が「失敗」と表示する不整合が
# 発生した）。バックグラウンドタスクとして起動し即座に応答を返す方式へ変更し、進捗・結果は
# `GET /training/status` でポーリングする。`model_promotions` を介さない自動承認ガバナンス
# （P9）という位置づけ自体は変えない。
_running_batches: dict[ModelType, asyncio.Task[None]] = {}
_last_results: dict[ModelType, dict[str, object]] = {}


@dataclass
class _ProgressState:
    """実行中バッチの進捗（🆕 P17、🔧 並列学習で複数銘柄が同時に running になりうる）:
    処理中の銘柄群・残り推定時間・既存比等の元データ."""

    started_at: float = field(default_factory=time.monotonic)
    current_tickers: list[str] = field(default_factory=list)
    total: int = 0
    processed: int = 0
    completed: int = 0
    activated: int = 0
    failed: int = 0


# `run_daily_training_batch` の `on_progress` コールバック経由で更新し、バッチ終了時にクリア
# する（`_running_batches`/`_last_results` 同様、インメモリ・サーバ再起動でリセット）。
_progress: dict[ModelType, _ProgressState] = {}


def _make_on_progress(model_type: ModelType) -> Callable[[TrainingProgressEvent], None]:
    """`run_daily_training_batch` からの進捗イベントを `_progress` へ反映するクロージャを返す."""

    def _handler(event: TrainingProgressEvent) -> None:
        state = _progress.setdefault(model_type, _ProgressState())
        state.total = event.total
        if event.status == "running":
            state.current_tickers.append(event.ticker)
            return
        if event.ticker in state.current_tickers:
            state.current_tickers.remove(event.ticker)
        state.processed = event.processed
        if event.status == "completed":
            state.completed += 1
            if event.activated:
                state.activated += 1
        else:
            state.failed += 1

    return _handler


async def _run_and_record(model_type: ModelType) -> None:
    """バックグラウンドで学習バッチを実行し、結果を `_last_results` へ記録する.

    手動トリガーは「いけるところまでいく」（🆕 P14、ユーザー確認済み）ため
    `manual_full_run_overrides` の上限を使う。celery-beat の自動定期実行
    （`tasks.py`）はこれを経由せず既存の上限のまま変更しない。
    """
    daily_limit, max_duration = manual_full_run_overrides(model_type)
    _progress.pop(model_type, None)
    try:
        summary = await run_daily_training_batch(
            model_type,
            daily_limit_override=daily_limit,
            max_duration_override=max_duration,
            on_progress=_make_on_progress(model_type),
        )
        _last_results[model_type] = {**summary.to_dict(), "error": None}
    except Exception as e:  # noqa: BLE001 — バックグラウンドタスクの想定外エラーを UI 側へ伝える
        logger.exception("学習バッチが異常終了しました（model_type=%s）", model_type)
        _last_results[model_type] = {"model_type": model_type, "error": str(e)}
    finally:
        _running_batches.pop(model_type, None)
        _progress.pop(model_type, None)


class EvaluatePromotionRequest(BaseModel):
    """`POST /api/registry/promotions/evaluate` のリクエストボディ.

    `lane="ml_pool"`（断面プール分類器、P5d）は held-out 検証指標で判定するため
    `horizon_days` を無視する（`evaluate_ml_pool_promotion` 参照）。
    """

    lane: Literal["mid_term", "short_term", "ml_pool"]
    challenger_version: str
    horizon_days: int = 20


class TrainingRunRequest(BaseModel):
    """`POST /api/registry/training/run` のリクエストボディ."""

    model_type: Literal["xgboost", "random_forest", "lstm", "transformer"]


def _is_per_ticker_lane(lane: object) -> bool:
    """銘柄別モデル（P9）の lane（`f"{model_type}:{ticker}"`）かどうかを判定する.

    システム全体レーン（`ml_pool`/`mid_term`/`short_term`）は `:` を含まないため、
    `:` の有無だけで一意に判別できる（`per_ticker_training_service._lane` 参照）。
    """
    return isinstance(lane, str) and ":" in lane


@router.get("/champions", response_model=ApiResponse[list[dict]], summary="系統別 champion 一覧")
async def champions() -> ApiResponse[list[dict]]:
    """全系統（lane）の現行 champion を返す.

    銘柄別モデル（P9、`lane=f"{model_type}:{ticker}"`）は品質ゲートで自動承認されるため
    数千件に上りうる。モデルラボの一覧は既存のシステムレーン（ml_pool/mid_term/short_term）
    比較用であり、それが埋もれないよう除外する（`per_ticker_training_service.py` 参照）。
    """
    rows = await list_champions()
    return ApiResponse.ok([r for r in rows if not _is_per_ticker_lane(r.get("lane"))])


@router.get("/promotions", response_model=ApiResponse[list[dict]], summary="昇格判定ログ")
async def promotions(
    lane: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
) -> ApiResponse[list[dict]]:
    """昇格ゲートの判定履歴を新しい順で返す（`applied` 済みか、提案止まりかも含む）.

    銘柄別モデル（P9）は `model_promotions` へ書き込まない（品質ゲートの自動承認は
    `model_champions` を直接差し替えるのみ）ため、本来この一覧に混入することは無いが、
    `champions()` と一貫した安全側のフィルタとして同様に除外する。
    """
    rows = await list_promotions(lane=lane, limit=limit)
    return ApiResponse.ok([r for r in rows if not _is_per_ticker_lane(r.get("lane"))])


@router.post("/promotions/evaluate", response_model=ApiResponse[dict], summary="昇格ゲートを手動評価")
async def evaluate(req: EvaluatePromotionRequest) -> ApiResponse[dict]:
    """challenger を champion と比較し `model_promotions` へ判定を記録する（提案のみ）."""
    if req.lane == POOL_LANE:
        result = await evaluate_ml_pool_promotion(req.challenger_version)
    else:
        result = await evaluate_promotion(req.lane, req.challenger_version, horizon_days=req.horizon_days)
    return ApiResponse.ok(result)


@router.post("/promotions/{promotion_id}/apply", response_model=ApiResponse[dict], summary="昇格を人手承認で適用")
async def apply(promotion_id: str) -> ApiResponse[dict]:
    """`propose_promote` かつ未適用の判定のみ champion を差し替える（唯一の昇格経路）."""
    applied = await apply_promotion(promotion_id)
    if not applied:
        return ApiResponse.fail("適用できません（判定が propose_promote でないか、既に適用済みです）")
    return ApiResponse.ok({"promotion_id": promotion_id, "applied": True})


@router.post("/training/run", response_model=ApiResponse[dict], summary="銘柄別モデルの学習バッチを起動")
async def run_training(req: TrainingRunRequest) -> ApiResponse[dict]:
    """指定モデルタイプの日次学習バッチをバックグラウンドで起動し、即座に応答する（🔧 P13h）.

    東証全銘柄のうち当日の上限まで（未学習優先→最も学習が古い順）を学習する
    （`per_ticker_training_service.run_daily_training_batch`）。品質ゲート合格分は
    `model_champions` を自動差し替える（P9、人手承認は不要）。モデルタイプにより
    数十秒〜数分かかりうる（xgboost/random_forest は5分、lstm/transformer は60分の
    1firing予算と同じ時間予算で動く）ため、完了を待たず即時に `started` を返す。
    進捗・結果は `GET /training/status` をポーリングして確認する。
    """
    model_type = req.model_type
    if model_type in _running_batches:
        return ApiResponse.ok({"model_type": model_type, "status": "already_running"})
    _last_results.pop(model_type, None)
    task = asyncio.create_task(_run_and_record(model_type))
    _running_batches[model_type] = task
    return ApiResponse.ok({"model_type": model_type, "status": "started"})


def _build_progress_payload(model_type: ModelType) -> dict[str, object] | None:
    """`_progress` の生状態から `GET /training/status` へ返す進捗ペイロードを組み立てる（🆕 P17）.

    処理中の銘柄群（🔧 並列学習により複数になりうる）・進捗率・残り推定時間
    （今回の処理速度からの単純な線形見積り）・既存比（品質ゲート通過率）を計算する。
    バッチが実行中でない場合は None。
    """
    state = _progress.get(model_type)
    if state is None:
        return None

    elapsed = time.monotonic() - state.started_at
    processed, total = state.processed, state.total
    eta_seconds = (elapsed / processed) * (total - processed) if processed > 0 and total > processed else None
    promotion_rate_pct = (state.activated / state.completed * 100) if state.completed > 0 else None

    return {
        "current_tickers": list(state.current_tickers),
        "processed": processed,
        "total": total,
        "failed_this_run": state.failed,
        "eta_seconds": eta_seconds,
        "promotion_rate_pct": promotion_rate_pct,
    }


@router.get("/training/status", response_model=ApiResponse[dict], summary="銘柄別モデル学習バッチの進捗・結果")
async def training_status(
    model_type: Literal["xgboost", "random_forest", "lstm", "transformer"] = Query(...),
) -> ApiResponse[dict]:
    """指定モデルタイプの学習バッチが実行中かどうか・本日ここまでの試行件数・直近の結果を返す.

    `TrainingTriggerPanel`（🔧 P13h）が `POST /training/run` 後にポーリングする想定。
    `progress`（🆕 P17）は実行中のみ値を持ち、処理中の銘柄・残り推定時間・既存比
    （品質ゲート通過率）等のライブ状態を表す。
    """
    running = model_type in _running_batches
    attempted_today = len(await get_attempted_tickers(today_jst(), model_type))
    return ApiResponse.ok(
        {
            "model_type": model_type,
            "running": running,
            "attempted_today": attempted_today,
            "last_result": _last_results.get(model_type),
            "progress": _build_progress_payload(model_type),
        }
    )


@router.get(
    "/model-stats/coverage", response_model=ApiResponse[list[ModelCoverage]], summary="銘柄別モデルの学習カバレッジ"
)
async def model_stats_coverage() -> ApiResponse[list[ModelCoverage]]:
    """モデルタイプ別に、東証全銘柄のうち学習済み・champion採用済みの件数と割合を返す（🆕 P15）."""
    return ApiResponse.ok(await model_stats_service.build_coverage())


@router.get(
    "/model-stats/quality", response_model=ApiResponse[list[QualityDistribution]], summary="銘柄別モデルの品質分布"
)
async def model_stats_quality() -> ApiResponse[list[QualityDistribution]]:
    """モデルタイプ別に、現行 champion の品質指標（skill・rmse）の生値リストを返す（🆕 P15）.

    ヒストグラムのビン分けはフロントエンドで行う。
    """
    return ApiResponse.ok(await model_stats_service.build_quality_distribution())


@router.get(
    "/model-stats/training-trend",
    response_model=ApiResponse[list[TrainingTrendPoint]],
    summary="銘柄別モデルの学習件数の推移",
)
async def model_stats_training_trend(
    days: int = Query(default=30, ge=1, le=365),
) -> ApiResponse[list[TrainingTrendPoint]]:
    """直近 `days` 日分の、日別・モデルタイプ別の学習試行件数（成功/失敗）推移を返す（🆕 P15）."""
    return ApiResponse.ok(await model_stats_service.build_training_trend(days))


@router.get("/drift", response_model=ApiResponse[list[dict]], summary="PSI ドリフト履歴")
async def drift(
    feature: str | None = Query(default=None, description="feature_snapshot の dotted path"),
    limit: int = Query(default=200, ge=1, le=1000),
) -> ApiResponse[list[dict]]:
    """特徴量分布ドリフト（PSI）の履歴を古い順で返す（モデルラボの推移グラフ用）."""
    return ApiResponse.ok(await list_drift_snapshots(feature_name=feature, limit=limit))


@router.get(
    "/pit-coverage", response_model=ApiResponse[PitCoverageStatus], summary="PIT特徴量スナップショットの収集進捗"
)
async def pit_coverage() -> ApiResponse[PitCoverageStatus]:
    """Vault由来ファンダメンタル・ニュースセンチメントの日次スナップショット収集進捗を返す（🆕 P29）.

    グループ（ファンダメンタル / keywordセンチメント / LLMセンチメント）ごとに、学習パネルへの
    投入に必要な `PIT_MIN_COVERAGE_DAYS` 営業日に対してあと何日分の収集が必要かを示す。
    """
    return ApiResponse.ok(await pit_coverage_service.build_pit_coverage_status())


@router.get("/ablations", response_model=ApiResponse[list[SourceAblationEntry]], summary="ソースアブレーション評価履歴")
async def ablations(
    quarter: str | None = Query(default=None, description='例: "2026Q3"'),
    excluded_source: str | None = Query(default=None),
) -> ApiResponse[list[SourceAblationEntry]]:
    """四半期ごとのソースアブレーション（除外時 − 全部入りのホールドアウト指標差分）を返す（🆕 P29）.

    「Vault由来の特徴量を足して本当に良くなったか」の客観的な判定材料（`source_ablations`）。
    """
    rows = await list_ablations(quarter=quarter, excluded_source=excluded_source)
    return ApiResponse.ok([SourceAblationEntry(**row) for row in rows])


# ---------------------------------------------------------------------------
# 🆕 学習対象設定（ポートフォリオ/ピック銘柄/全銘柄/カスタムリスト・並列学習プロセス数上限）
# ---------------------------------------------------------------------------


@router.get(
    "/training-settings", response_model=ApiResponse[TrainingTargetSettingsResponse], summary="学習対象設定を取得"
)
async def get_training_settings() -> ApiResponse[TrainingTargetSettingsResponse]:
    """学習対象モード・並列学習プロセス数上限を返す（未保存なら `all`/4 の既定値）."""
    settings = await training_target_service.get_settings()
    return ApiResponse.ok(
        TrainingTargetSettingsResponse(
            target_mode=settings.target_mode, max_parallel_workers=settings.max_parallel_workers
        )
    )


@router.put(
    "/training-settings", response_model=ApiResponse[TrainingTargetSettingsResponse], summary="学習対象設定を更新"
)
async def update_training_settings(
    req: TrainingTargetSettingsUpdateRequest,
) -> ApiResponse[TrainingTargetSettingsResponse]:
    """学習対象モード・並列数上限を更新する（DB即時反映、`.env` 方式と異なり再起動不要）."""
    settings = await training_target_service.update_settings(
        target_mode=req.target_mode, max_parallel_workers=req.max_parallel_workers
    )
    return ApiResponse.ok(
        TrainingTargetSettingsResponse(
            target_mode=settings.target_mode, max_parallel_workers=settings.max_parallel_workers
        )
    )


async def _resolve_training_target_tickers() -> list[TrainingTargetTickerEntry]:
    """カスタムリストの銘柄を銘柄マスタで名称・業種解決し、追加日時順で返す共通処理."""
    added_at_map = await training_target_db.get_custom_ticker_added_at_map()
    if not added_at_map:
        return []
    master_by_code = {t.code: t for t in await _get_ticker_master()}
    entries = [
        TrainingTargetTickerEntry(
            code=code,
            name=master_by_code[code].name if code in master_by_code else code,
            sector=master_by_code[code].sector if code in master_by_code else None,
            added_at=added_at,
        )
        for code, added_at in added_at_map.items()
    ]
    entries.sort(key=lambda e: e.added_at)
    return entries


@router.get(
    "/training-target-tickers",
    response_model=ApiResponse[list[TrainingTargetTickerEntry]],
    summary="学習対象カスタムリストの一覧を取得",
)
async def get_training_target_tickers() -> ApiResponse[list[TrainingTargetTickerEntry]]:
    """カスタムリストの銘柄一覧を返す（銘柄マスタに存在しないコードも `added_at` はそのまま返す）."""
    return ApiResponse.ok(await _resolve_training_target_tickers())


@router.put(
    "/training-target-tickers",
    response_model=ApiResponse[list[TrainingTargetTickerEntry]],
    summary="学習対象カスタムリストを全置換",
)
async def update_training_target_tickers(
    req: TrainingTargetTickersUpdateRequest,
) -> ApiResponse[list[TrainingTargetTickerEntry]]:
    """ポップアップダイアログのチェック結果を保存する（既存銘柄の追加日時は維持したまま全置換）."""
    await training_target_db.replace_custom_tickers(req.codes)
    return ApiResponse.ok(await _resolve_training_target_tickers())


@router.get(
    "/ticker-universe", response_model=ApiResponse[list[TickerUniverseEntry]], summary="全銘柄一覧（業種・出来高付き）"
)
async def ticker_universe(
    sector: str | None = Query(default=None),
    sort: TickerUniverseSort = Query(default="code_asc"),
    q: str | None = Query(default=None),
) -> ApiResponse[list[TickerUniverseEntry]]:
    """カスタムリスト選択ダイアログ用の全銘柄一覧（業種フィルタ・出来高ソート・部分一致検索付き）を返す."""
    return ApiResponse.ok(await list_ticker_universe(sector=sector, sort=sort, q=q))
