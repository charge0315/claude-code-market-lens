"""学習対象ユニバースの決定ロジック（🆕 学習対象設定）.

個別銘柄モデル（xgboost/random_forest/lstm/transformer, `per_ticker_training_service.py`）と
プールモデル（ml_pool, `pool_training_service.py`）の両方の候補選定に同じユニバースを使う。
設定は DB（`training_target_settings`/`training_target_tickers`）で即時反映し、`.env` 方式
（`config_store.py`、再起動必須）は使わない。行が無い場合は `target_mode="all"` にフォール
バックし、既存の「東証全銘柄固定」動作と完全後方互換にする。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Literal, cast

from backend.models.stocks import TickerInfo
from backend.services.data.data_fetcher import _get_ticker_master
from backend.services.db import portfolio_db, training_target_db
from backend.services.jst_time import JST
from backend.services.ledger import prediction_ledger

TrainingTargetMode = Literal["portfolio", "picked", "all", "custom"]
_VALID_MODES: tuple[TrainingTargetMode, ...] = ("portfolio", "picked", "all", "custom")

_DEFAULT_MODE: TrainingTargetMode = "all"
_DEFAULT_MAX_PARALLEL_WORKERS = 4
_MIN_MAX_PARALLEL_WORKERS = 1
_MAX_MAX_PARALLEL_WORKERS = 16

# 「ピックした銘柄」モードの累積期間（直近何日分のピックを学習対象にするか、ユーザー確認済み）。
_PICKED_LOOKBACK_DAYS = 30


@dataclass(frozen=True)
class TrainingTargetSettings:
    target_mode: TrainingTargetMode
    max_parallel_workers: int


def _clamp_max_parallel_workers(value: int) -> int:
    return max(_MIN_MAX_PARALLEL_WORKERS, min(_MAX_MAX_PARALLEL_WORKERS, value))


async def get_settings() -> TrainingTargetSettings:
    """学習対象設定を返す（未保存なら `all`/4 の既定値、既存動作と完全後方互換）."""
    row = await training_target_db.get_training_settings()
    if row is None:
        return TrainingTargetSettings(target_mode=_DEFAULT_MODE, max_parallel_workers=_DEFAULT_MAX_PARALLEL_WORKERS)

    raw_mode = str(row.get("target_mode") or _DEFAULT_MODE)
    mode = cast("TrainingTargetMode", raw_mode) if raw_mode in _VALID_MODES else _DEFAULT_MODE
    raw_workers = row.get("max_parallel_workers")
    workers = int(raw_workers) if isinstance(raw_workers, int) else _DEFAULT_MAX_PARALLEL_WORKERS
    return TrainingTargetSettings(target_mode=mode, max_parallel_workers=_clamp_max_parallel_workers(workers))


async def update_settings(
    *, target_mode: TrainingTargetMode | None = None, max_parallel_workers: int | None = None
) -> TrainingTargetSettings:
    """学習対象設定を更新する（省略した項目は現在値を維持する部分更新）."""
    current = await get_settings()
    new_mode = target_mode if target_mode is not None else current.target_mode
    new_workers = (
        _clamp_max_parallel_workers(max_parallel_workers)
        if max_parallel_workers is not None
        else current.max_parallel_workers
    )
    await training_target_db.upsert_training_settings(target_mode=new_mode, max_parallel_workers=new_workers)
    return TrainingTargetSettings(target_mode=new_mode, max_parallel_workers=new_workers)


async def resolve_training_universe() -> list[TickerInfo]:
    """学習対象モードに応じたユニバースを返す（個別銘柄モデル・プールモデル共通の唯一の入口）.

    ポートフォリオ/ピック銘柄/カスタムリストが空集合の場合でも全銘柄へフォールバックせず、
    そのまま空リストを返す（フォールバックすると設定自体が無意味になるため）。呼び出し側
    （`_select_candidates`/`run_pool_training`）は「学習対象 0 件」として自然にスキップする。
    """
    settings = await get_settings()
    master = await _get_ticker_master()

    if settings.target_mode == "all":
        return master

    by_code = {t.code: t for t in master}

    if settings.target_mode == "portfolio":
        holdings = await portfolio_db.list_holdings()
        codes = {str(h["symbol"]) for h in holdings}
        return [by_code[c] for c in codes if c in by_code]

    if settings.target_mode == "picked":
        issued_from = (datetime.now(JST) - timedelta(days=_PICKED_LOOKBACK_DAYS)).date().isoformat()
        codes = await prediction_ledger.list_picked_symbols_since(issued_from)
        return [by_code[c] for c in codes if c in by_code]

    # "custom": 銘柄マスタに存在しないコードは黙って除外する（規約変更や上場廃止等）。
    custom_codes = await training_target_db.list_custom_tickers()
    return [by_code[c] for c in custom_codes if c in by_code]


async def get_priority_override_map() -> dict[str, str]:
    """`custom` モード時のみ、銘柄ごとの学習対象追加日時を返す（差分学習の優先度昇格用、要件6）.

    学習対象への追加が最終学習日時より後なら「未学習」扱いにして最優先候補に昇格させる
    （`_select_candidates` 側で使う）。他モードには「追加日時」という概念が無いため空 dict。
    """
    settings = await get_settings()
    if settings.target_mode != "custom":
        return {}
    return await training_target_db.get_custom_ticker_added_at_map()
