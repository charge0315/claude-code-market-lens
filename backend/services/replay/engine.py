"""過去日リプレイのループ本体（🆕 P37）.

リプレイ日 D ごとに、D の大引け時点の窓口（`AsOfView`）だけを使って次を順に行う:

1. **答え合わせ**: 未決着のピックを、D までに確定したバーで解決する（本番と同じ
   `outcome_resolver.build_outcomes` を `today=D` で呼ぶ。ベンチマークは TOPIX 連動 ETF 1306）。
2. **再学習**: `retrain_every_bdays` 営業日ごとに、D の時点でラベルが確定しているデータだけで
   断面プールモデルを学び直す（`replay/ml.py`）。
3. **ピック**: 本番と同じ規則で候補プール → 採点 → ショートリスト → E1 → 3 値（`replay/selection.py`）。
4. 進捗カーソル（`cursor_date`）を D に進める。

各日の書き込みは冪等なので、途中で落ちても `cursor_date` の翌営業日から再開すればよい
（再開時はプールモデルを最初に学び直す）。停止要求は `replay_runs.status = 'stopping'`。
"""

from __future__ import annotations

import asyncio
import dataclasses
import logging
import os
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Final

import pandas as pd

from backend.services.data.jquants_errors import JQuantsError
from backend.services.data.ranking_service import RANKING_POOL_SIZE, rankings_from_bars
from backend.services.db import replay_db
from backend.services.jst_time import JST
from backend.services.learning.pool_model import POOL_LANE
from backend.services.learning.pool_training_service import PoolClassifier
from backend.services.ledger.outcome_resolver import HORIZON_SETS, build_outcomes
from backend.services.picks.pipeline import POOL_CONFIG, order_candidate_codes
from backend.services.registry.model_registry import ensure_registered
from backend.services.replay import learning
from backend.services.replay.ml import FeatureCache, ReplayMlConfig, score_provider_at, train_at
from backend.services.replay.price_store import AsOfView, PriceStore
from backend.services.replay.selection import score_candidates, select_picks

logger = logging.getLogger(__name__)

# 決着のベンチマーク。本番は yfinance の TOPIX だが、リプレイは同じ J-Quants 日足に含まれる
# TOPIX 連動 ETF で代用し、時点整合をキャッシュ内で完結させる。
BENCHMARK_CODE: Final[str] = "1306"
# 決着の計算に渡す履歴は発行日の少し前から（全期間を毎日スライスすると遅いため）。
_OUTCOME_LOOKBACK_DAYS: Final[int] = 10
# 上場廃止等でいつまでも決着しないピックを打ち切る暦日数（中長期 60 営業日 ≒ 90 暦日 + 余裕）。
_EXPIRE_AFTER_DAYS: Final[int] = 150
HORIZON_TYPES: Final[tuple[str, ...]] = ("mid_term", "short_term")
_MODEL_DIR: Final[Path] = Path(__file__).resolve().parents[3] / "data" / "models"


@dataclass(frozen=True)
class ReplayConfig:
    """1 回のリプレイ実行の設定（`replay_runs.config` に JSON で保存）."""

    retrain_every_bdays: int = 20
    ml: ReplayMlConfig = field(default_factory=ReplayMlConfig)

    def to_dict(self) -> dict[str, object]:
        return dataclasses.asdict(self)

    @classmethod
    def from_dict(cls, raw: Mapping[str, object]) -> ReplayConfig:
        ml_raw = raw.get("ml")
        ml = (
            ReplayMlConfig(**{k: int(v) for k, v in ml_raw.items() if isinstance(v, int)})
            if isinstance(ml_raw, dict)
            else ReplayMlConfig()
        )
        every = raw.get("retrain_every_bdays")
        return cls(retrain_every_bdays=every if isinstance(every, int) else 20, ml=ml)


@dataclass
class _ModelState:
    """リプレイ中の断面プールモデル（再学習のたびに差し替える、ループ内のみの可変状態）."""

    clf: PoolClassifier | None = None
    version: str | None = None
    days_since_retrain: int = 0


def _now() -> str:
    return datetime.now(JST).isoformat(timespec="seconds")


def _pick_status(horizon_type: str, n_outcomes: int, state: str, issued_at: str, today: str) -> str:
    if state in ("unfilled", "no_data"):
        return state
    if state == "filled" and n_outcomes >= len(HORIZON_SETS[horizon_type]):
        return "filled"
    if (date.fromisoformat(today) - date.fromisoformat(issued_at)).days > _EXPIRE_AFTER_DAYS:
        return "expired"
    return "pending"


async def resolve_pending(run_id: str, view: AsOfView, resolved_counts: dict[str, int]) -> int:
    """未決着ピックを D までのバーで解決し、状態が変わった件数を返す."""
    bench_all = view.history(BENCHMARK_CODE)
    changed = 0
    for p in await replay_db.list_pending_picks(run_id):
        pick_id = str(p["pick_id"])
        issued_at = str(p["issued_at"])
        horizon_type = str(p["horizon_type"])
        start = pd.Timestamp(issued_at) - pd.Timedelta(days=_OUTCOME_LOOKBACK_DAYS)
        bars = view.history(str(p["symbol"]))
        outcomes, state = build_outcomes(
            horizon_type=horizon_type,
            issued_at=issued_at,
            entry=float(str(p["entry"])),
            stop=float(str(p["stop"])),
            target=float(str(p["target"])),
            bars=bars[bars.index >= start],
            bench_bars=bench_all[bench_all.index >= start],
            today=view.as_of,
        )
        status = _pick_status(horizon_type, len(outcomes), state, issued_at, view.as_of)
        if len(outcomes) == resolved_counts.get(pick_id, 0) and status == "pending":
            continue
        await replay_db.record_outcomes(run_id, pick_id, outcomes, resolved_on=view.as_of, status=status)
        resolved_counts[pick_id] = len(outcomes)
        changed += 1
    return changed


async def _maybe_retrain(
    run_id: str, view: AsOfView, cache: FeatureCache, cfg: ReplayConfig, model: _ModelState
) -> None:
    if model.clf is not None and model.days_since_retrain < cfg.retrain_every_bdays:
        model.days_since_retrain += 1
        return
    trained = await asyncio.to_thread(train_at, view, cache, cfg.ml)
    model.days_since_retrain = 1
    if trained is None:
        return
    model.clf, metrics = trained
    model.version = f"replay-pool@{view.as_of}"
    await replay_db.insert_retrain(run_id, trained_on=view.as_of, model_version=model.version, metrics=dict(metrics))


async def pick_for_day(run_id: str, view: AsOfView, cache: FeatureCache, model: _ModelState) -> int:
    """D の大引け時点の情報でピックを作り台帳へ書く。書いたピック数を返す."""
    prev = view.previous_trading_date(view.as_of)
    if prev is None:
        return 0
    try:
        rankings = rankings_from_bars(view.as_of, view.bars_on(view.as_of), view.bars_on(prev), {}, RANKING_POOL_SIZE)
    except JQuantsError:  # 比較可能な銘柄が 1 つも無い日（データ欠け）はピックしない
        return 0
    provider = score_provider_at(view, cache, model.clf)
    total = 0
    for horizon_type in HORIZON_TYPES:
        codes = order_candidate_codes(rankings, horizon_type, POOL_CONFIG[horizon_type]["pool_limit"])
        candidates = await asyncio.to_thread(score_candidates, view, codes, provider)
        picks, _rejected = select_picks(candidates, horizon_type, issued_at=view.as_of)
        await replay_db.insert_picks(run_id, picks, model_version=model.version if model.clf else None)
        total += len(picks)
    return total


async def _should_stop(run_id: str) -> bool:
    run = await replay_db.get_run(run_id)
    return run is None or run.get("status") == "stopping"


async def run_replay(run_id: str, store: PriceStore) -> str:
    """`replay_runs` の設定どおりにリプレイを進める（再開可能）。最終状態を返す."""
    run = await replay_db.get_run(run_id)
    if run is None:
        raise ValueError(f"リプレイ {run_id} が見つかりません")
    if run.get("status") == "stopping":
        # 子プロセスが走り出す前に停止要求が来ていた。running で上書きして要求を失わないように。
        await replay_db.update_run(run_id, status="stopped")
        return "stopped"
    config = run.get("config")
    cfg = ReplayConfig.from_dict(config if isinstance(config, dict) else {})
    cursor = run.get("cursor_date")
    dates = [
        d
        for d in store.trading_dates_between(str(run["start_date"]), str(run["end_date"]))
        if not isinstance(cursor, str) or d > cursor
    ]
    await replay_db.update_run(run_id, status="running", pid=os.getpid(), heartbeat_at=_now(), error=None)
    try:
        cache = await asyncio.to_thread(FeatureCache.build, store)
        model = _ModelState()
        resolved_counts: dict[str, int] = {}
        for i, day in enumerate(dates):
            view = store.view(day)
            await resolve_pending(run_id, view, resolved_counts)
            await _maybe_retrain(run_id, view, cache, cfg, model)
            n = await pick_for_day(run_id, view, cache, model)
            await replay_db.update_run(run_id, cursor_date=day, heartbeat_at=_now())
            if i % 20 == 0:
                logger.info("リプレイ %s: %s を処理（%d/%d 日、ピック %d 件）", run_id, day, i + 1, len(dates), n)
            if await _should_stop(run_id):
                await replay_db.update_run(run_id, status="stopped")
                return "stopped"
        summary = await learning.compute_summary(run_id)
        summary["challenger_version"] = await register_final_model(run_id, model)
        await replay_db.update_run(run_id, status="completed", summary=summary, heartbeat_at=_now())
        return "completed"
    except Exception as exc:
        logger.exception("リプレイ %s が失敗しました", run_id)
        await replay_db.update_run(run_id, status="failed", error=f"{type(exc).__name__}: {exc}")
        raise


async def register_final_model(run_id: str, model: _ModelState) -> str | None:
    """最後に学び直したプールモデルを lane="ml_pool" の challenger として登録する（champion にはしない）.

    本番の昇格は既存の人手承認ゲート（`promotion.evaluate_ml_pool_promotion`、held-out AUC/Brier
    比較）を通してのみ行う。`bootstrap_champion_if_missing` は意図的に呼ばない
    （リプレイ由来モデルが無審査で本番入りしないように）。
    """
    if model.clf is None or model.version is None:
        return None
    trained_on = model.version.split("@", 1)[-1]
    version = f"replay-{run_id[:8]}-{trained_on}"
    artifact_path = str(_MODEL_DIR / f"{version}.joblib")
    await asyncio.to_thread(model.clf.save, artifact_path)
    retrains = await replay_db.list_retrains(run_id)
    last_metrics = retrains[-1]["metrics"] if retrains else {}
    val_metrics: dict[str, object] = {
        **(last_metrics if isinstance(last_metrics, dict) else {}),
        "source": "replay",
        "replay_run_id": run_id,
    }
    await ensure_registered(
        version,
        lane=POOL_LANE,
        val_metrics=val_metrics,
        feature_list=model.clf.feature_cols,
        artifact_path=artifact_path,
    )
    return version


def default_log_dir() -> Path:
    return Path(__file__).resolve().parents[3] / "data" / "replay" / "logs"
