"""Celery タスク定義.

`celery -A backend.celery_app worker` はこのモジュールを include して @task を登録する。
非同期のコアロジックは `asyncio.run()` でラップして呼ぶ（Celery ワーカーは FastAPI の
イベントループを共有しない）。beat スケジュールは `celery_app._BEAT_SCHEDULE` で一元管理する
（手動 `.delay()` 投入はしない）。
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, time

from backend.celery_app import celery_app
from backend.services.jst_time import JST

logger = logging.getLogger(__name__)

# 東証の立会時間（大引け 15:00、監視は 15:30 まで。祝日は非対応 — `plans/01_PRD` PF-2）。
_MARKET_OPEN_JST = time(9, 0)
_MARKET_CLOSE_JST = time(15, 30)


def _is_weekday_jst() -> bool:
    """現在の曜日が JST 基準で平日かを判定する（祝日は非対応）."""
    return datetime.now(JST).weekday() < 5  # 5=土, 6=日


def _is_market_hours_jst() -> bool:
    """現在時刻が JST 基準の平日・東証立会時間内かを判定する（祝日は非対応）."""
    if not _is_weekday_jst():
        return False
    return _MARKET_OPEN_JST <= datetime.now(JST).time() <= _MARKET_CLOSE_JST


@celery_app.task(name="backend.tasks.ping")
def ping() -> str:
    """ワーカー疎通確認用の最小タスク."""
    return "pong"


@celery_app.task(name="backend.tasks.run_picks_task")
def run_picks_task(horizon_type: str) -> dict[str, object]:
    """指定系統（mid_term / short_term）のピックを生成し台帳化する（JST 08:50）."""
    from backend.services.picks.pipeline import run_picks

    result = asyncio.run(run_picks(horizon_type))
    return {"status": result.status, "picks": len(result.picks), "rejected": len(result.rejected)}


@celery_app.task(name="backend.tasks.resolve_pick_outcomes_task")
def resolve_pick_outcomes_task() -> dict[str, int]:
    """未決着ピックを古い順に解決して `pick_outcomes` へ書き込む（夜間）."""
    from backend.services.ledger.outcome_resolver import resolve_pending

    s = asyncio.run(resolve_pending(max_picks=20))
    return {
        "resolved_picks": s.resolved_picks,
        "written_outcomes": s.written_outcomes,
        "unfilled": s.unfilled,
        "failed": s.failed,
    }


@celery_app.task(name="backend.tasks.update_eval_metrics_task")
def update_eval_metrics_task() -> dict[str, object]:
    """決着後に評価指標（較正 / IC / 成績）を再集計して `eval_snapshots` へ追記する（夜間）."""
    from backend.services.ledger.eval_service import run_eval_batch

    return {"scopes": list(asyncio.run(run_eval_batch()))}


@celery_app.task(name="backend.tasks.sync_trends_task")
def sync_trends_task() -> dict[str, object]:
    """Trend Tracking Agent を同期する（1 日 4 回。TTL 3h 内は再利用）."""
    from backend.services.data.trend.sync_service import sync_trends

    snap = asyncio.run(sync_trends())
    return {"status": snap.status, "trends": len(snap.trends), "signals": snap.signal_count}


@celery_app.task(name="backend.tasks.run_drift_check_task")
def run_drift_check_task() -> dict[str, object]:
    """特徴量分布ドリフト（PSI）を週次で計測する（N5）.

    ベースライン = 直近 90〜30 日前、直近 = 過去 30 日。台帳が薄いうちは
    `run_drift_batch` がサンプル不足の特徴量を自然にスキップする。
    """
    from datetime import datetime, timedelta

    from backend.services.jst_time import JST
    from backend.services.registry.drift import run_drift_batch

    now = datetime.now(JST)
    results = asyncio.run(
        run_drift_batch(
            baseline_start=(now - timedelta(days=90)).isoformat(timespec="seconds"),
            baseline_end=(now - timedelta(days=30)).isoformat(timespec="seconds"),
            current_start=(now - timedelta(days=30)).isoformat(timespec="seconds"),
            current_end=now.isoformat(timespec="seconds"),
        )
    )
    return {"checked": len(results), "drifted": sum(1 for r in results if r.drift_flag)}


@celery_app.task(name="backend.tasks.run_promotion_evaluation_task")
def run_promotion_evaluation_task() -> dict[str, str]:
    """全 lane の challenger（champion 以外の登録済みバージョン）を週次で評価する（N1）.

    判定は `model_promotions` へ記録するのみ（`applied=0`）。champion の実差し替えは
    `POST /api/registry/promotions/{id}/apply` の人手承認でのみ行う（自動昇格 OFF）。
    """
    from backend.services.registry.promotion import evaluate_all_challengers

    return asyncio.run(evaluate_all_challengers())


@celery_app.task(name="backend.tasks.run_pool_training_task")
def run_pool_training_task() -> dict[str, object]:
    """断面プール分類器（lane="ml_pool"）を月次で再学習する（P5d）.

    初回バージョンは無条件で champion になる（N1 ブートストラップ）。2 本目以降は登録のみ
    行い、`run_promotion_evaluation_task`（週次、`evaluate_all_challengers` が ml_pool lane も
    走査する）の提案を経て `POST /api/registry/promotions/{id}/apply` の人手承認で昇格する。
    """
    from backend.services.learning.pool_training_service import run_pool_training

    summary = asyncio.run(run_pool_training())
    return summary.to_dict()


@celery_app.task(name="backend.tasks.run_portfolio_monitor_task")
def run_portfolio_monitor_task() -> dict[str, object] | None:
    """保有銘柄を AI 判定し `portfolio_signals` へ記録する（🆕 P7b、PF-2、場中 5 分周期）.

    立会時間外（`_is_market_hours_jst()` が False）は判定のみの軽い早期 return（`run_signal_scan_task`
    等の既存の自走タスクと同じ理由 — 価格データが古い可能性があるため場中のみ実行）。
    判定は `portfolio_signals` へ `status="proposed"` で記録するだけで、実際の売買は一切行わない。
    """
    from backend.services.portfolio.signal_service import run_portfolio_monitor

    if not _is_market_hours_jst():
        return None
    signal_ids = asyncio.run(run_portfolio_monitor())
    return {"signal_ids": signal_ids, "count": len(signal_ids)}


@celery_app.task(name="backend.tasks.run_xgboost_training_batch_task")
def run_xgboost_training_batch_task() -> dict[str, object]:
    """銘柄別 XGBoost モデルの日次学習バッチを1回分だけ進める（P9、5 分間隔）.

    品質ゲート合格時は `model_champions`（`lane=f"xgboost:{ticker}"`）を自動差し替える
    （`promoted_by="quality_gate"`）。ml_pool/mid_term/short_term レーンとは別格の
    自動承認ガバナンス（ユーザー確認済み、`per_ticker_training_service.py` docstring 参照）。
    """
    from backend.services.learning.per_ticker_training_service import run_daily_training_batch

    summary = asyncio.run(run_daily_training_batch("xgboost"))
    return summary.to_dict()


@celery_app.task(name="backend.tasks.run_random_forest_training_batch_task")
def run_random_forest_training_batch_task() -> dict[str, object]:
    """銘柄別 RandomForest モデルの日次学習バッチを1回分だけ進める（P9、5 分間隔）."""
    from backend.services.learning.per_ticker_training_service import run_daily_training_batch

    summary = asyncio.run(run_daily_training_batch("random_forest"))
    return summary.to_dict()


@celery_app.task(name="backend.tasks.run_lstm_training_batch_task")
def run_lstm_training_batch_task() -> dict[str, object]:
    """銘柄別 LSTM モデルの日次学習バッチを1回分だけ進める（P9、1 時間間隔、torch 学習のため重い）."""
    from backend.services.learning.per_ticker_training_service import run_daily_training_batch

    summary = asyncio.run(run_daily_training_batch("lstm"))
    return summary.to_dict()


@celery_app.task(name="backend.tasks.run_transformer_training_batch_task")
def run_transformer_training_batch_task() -> dict[str, object]:
    """銘柄別 Transformer モデルの日次学習バッチを1回分だけ進める（P9、1 時間間隔、torch 学習のため重い）."""
    from backend.services.learning.per_ticker_training_service import run_daily_training_batch

    summary = asyncio.run(run_daily_training_batch("transformer"))
    return summary.to_dict()


@celery_app.task(name="backend.tasks.run_daily_note_draft_task")
def run_daily_note_draft_task() -> dict[str, object]:
    """本日のピック生成完了後、有料note配信用の下書きを自動生成する（🆕 JST 08:15）.

    生成のみ行い、配信（note.comへの投稿）は行わない — 人間がレビュー・承認した上で
    手動投稿する半自動フロー（`services/notes/note_service.py` docstring 参照）。
    """
    from backend.services.notes.note_service import generate_today

    note = asyncio.run(generate_today())
    return {"note_id": note.note_id, "status": note.status, "has_price_mention_warning": note.has_price_mention_warning}


@celery_app.task(name="backend.tasks.run_eod_review_task")
def run_eod_review_task() -> dict[str, object]:
    """本日の `portfolio_signals` を集計し大引け後レビューを生成する（🆕 P7d、JST 16:31）.

    `run_eod_review` 自体が `review_date` PK で冪等（既にあれば再利用）なので、ここでは
    weekday ガードを掛けない — 非営業日は判定 0 件のため軽量なフォールバック文言が入るだけ。
    """
    from backend.services.portfolio.eod_review_service import run_eod_review

    review = asyncio.run(run_eod_review())
    return {"review_date": review.review_date, "heuristics": len(review.learned_heuristics)}
