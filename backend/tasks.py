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
    """指定系統（mid_term / short_term）のピックを生成し台帳化する（JST 07:30/07:32）.

    celery-beat は長時間停止後の再起動時、due 判定した全エントリを即時発火する
    （2026-09-20 に実際発生）。この際、休場日（土日）にもかかわらず本タスクが平日判定
    （`_is_weekday_jst`）を持たなかったため、金曜終値ベースの無効なピックが実際に生成される
    事故も同日発生した。`pipeline.run_picks` 自体はこれらのガードを持たない（`POST
    /api/picks/run` 経由の手動再生成は意図的に休場日でも毎回新規生成させたいため）ので、
    beat 起点の本タスクでのみ「休場日なら skip」「本日分の既存ピックがあれば skip」を行う。
    """
    from backend.services.ledger import prediction_ledger as pl
    from backend.services.picks.pipeline import run_picks

    if not _is_weekday_jst():
        return {"status": "skipped_non_trading_day", "picks": 0, "rejected": 0}

    async def _run() -> dict[str, object]:
        today = datetime.now(JST).date().isoformat()
        already_issued = await pl.list_picks(horizon_type=horizon_type, issued_from=f"{today}T00:00:00", limit=1)
        if already_issued:
            return {"status": "skipped_already_issued_today", "picks": 0, "rejected": 0}
        result = await run_picks(horizon_type)
        return {"status": result.status, "picks": len(result.picks), "rejected": len(result.rejected)}

    return asyncio.run(_run())


@celery_app.task(name="backend.tasks.collect_pit_fundamental_snapshot_task")
def collect_pit_fundamental_snapshot_task() -> dict[str, object]:
    """当日分のファンダメンタル PIT スナップショットを収集する（🆕 P29、大引け後）.

    `PIT_SNAPSHOT_ENABLED=false` なら即 skip（フェイルソフト、既定は有効）。
    `plans/03_システム設計` §3.6 / §3.7。
    """
    from backend.config import settings
    from backend.services.learning.pit_snapshot_service import collect_fundamental_snapshots, resolve_snapshot_codes

    if not settings.pit_snapshot_enabled:
        return {"status": "skipped_disabled"}

    async def _run() -> dict[str, object]:
        codes = await resolve_snapshot_codes(settings.pit_snapshot_scope)
        stats = await collect_fundamental_snapshots(codes)
        return {"scope": settings.pit_snapshot_scope, "attempted": stats.attempted, "collected": stats.collected}

    return asyncio.run(_run())


@celery_app.task(name="backend.tasks.collect_pit_sentiment_snapshot_task")
def collect_pit_sentiment_snapshot_task() -> dict[str, object]:
    """当日分の keyword センチメント PIT スナップショットを収集する（🆕 P29、大引け後）.

    LLM センチメントは追加収集しない — ピック生成（`run_picks_task`）の一部として
    `orchestrator.py` が既に shortlist 分を副産物記録済み（`plans/03_システム設計` §3.7.7）。
    """
    from backend.config import settings
    from backend.services.learning.pit_snapshot_service import (
        collect_sentiment_snapshots_keyword,
        resolve_snapshot_codes,
    )

    if not settings.pit_snapshot_enabled:
        return {"status": "skipped_disabled"}

    async def _run() -> dict[str, object]:
        codes = await resolve_snapshot_codes(settings.pit_sentiment_scope)
        stats = await collect_sentiment_snapshots_keyword(codes)
        return {"scope": settings.pit_sentiment_scope, "attempted": stats.attempted, "collected": stats.collected}

    return asyncio.run(_run())


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


@celery_app.task(name="backend.tasks.run_source_ablation_task")
def run_source_ablation_task() -> dict[str, object]:
    """PIT 由来の特徴量グループについて四半期ごとのソースアブレーション評価を行う（🆕 P29）.

    月次（`run_pool_training_task` と同日）に発火するが、実行するのは四半期開始月
    （1/4/7/10 月）のみ — celery-beat の crontab は「N ヶ月ごと」を直接表現できないため、
    タスク内部でガードする。`source_ablations`（`0001_baseline` で定義済みだが書き込む実装が
    存在しなかった）の初実装。「Vault 由来の特徴量を足して本当に良くなったか」を判定する。
    """
    from backend.services.learning.pool_training_service import default_as_of_dates

    if datetime.now(JST).month not in (1, 4, 7, 10):
        return {"status": "skipped_not_quarter_start"}

    async def _run() -> dict[str, object]:
        from backend.services.learning.panel_feature_service import build_panel
        from backend.services.ledger.ablation_service import run_all_pit_ablations

        panel = await build_panel(default_as_of_dates())
        if panel.empty:
            return {"status": "skipped_empty_panel"}
        results = await run_all_pit_ablations(panel)
        return {"status": "done", "groups_evaluated": [r.excluded_source for r in results]}

    return asyncio.run(_run())


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
    """本日のピック生成完了後、有料note配信用の下書きを自動生成する（🆕 JST 08:05）.

    生成後、Obsidian(.md)・SingleHTML への書き出しも行う（`Daily/AlphaForge/<日付>/`、
    ユーザー指示: 毎朝Obsidianで内容を確認し note.com へ手動で貼り付ける運用のため）。
    note.comへの投稿そのものは公式APIが無いため人間が行う（半自動フロー、
    `services/notes/note_service.py` docstring 参照）。
    """
    from backend.services.notes.note_export import export_note_files
    from backend.services.notes.note_service import generate_today

    async def _run() -> dict[str, object]:
        note = await generate_today()
        note_dir = await export_note_files(note)
        return {
            "note_id": note.note_id,
            "status": note.status,
            "has_price_mention_warning": note.has_price_mention_warning,
            "note_dir": str(note_dir),
        }

    return asyncio.run(_run())


@celery_app.task(name="backend.tasks.generate_vault_report_task")
def generate_vault_report_task() -> dict[str, object]:
    """本日のAIピックの詳細アーカイブレポートをVaultへ保存する（🆕 JST 08:25）.

    note下書き生成（JST 08:15）の後に走らせ、同じ台帳データから個人用アーカイブを作る。
    `Daily/AlphaForge/<日付>/` はMarket Lens出力（`Daily/YYYY-MM-DD.md`）と衝突しない専用パス。
    """
    from backend.services.vault_report.report_service import generate_report_for_date

    result = asyncio.run(generate_report_for_date())
    return result.model_dump()


@celery_app.task(name="backend.tasks.run_eod_review_task")
def run_eod_review_task() -> dict[str, object]:
    """本日の `portfolio_signals` を集計し大引け後レビューを生成する（🆕 P7d、JST 16:31）.

    `run_eod_review` 自体が `review_date` PK で冪等（既にあれば再利用）なので、ここでは
    weekday ガードを掛けない — 非営業日は判定 0 件のため軽量なフォールバック文言が入るだけ。
    """
    from backend.services.portfolio.eod_review_service import run_eod_review

    review = asyncio.run(run_eod_review())
    return {"review_date": review.review_date, "heuristics": len(review.learned_heuristics)}


@celery_app.task(name="backend.tasks.generate_pipeline_log_task")
def generate_pipeline_log_task() -> dict[str, object]:
    """本日のパイプライン実行結果（候補プール〜モデル入れ替え）を日次ログとしてVaultへ保存する
    （🆕 P30、JST 17:00）.

    ピック生成（07:30〜）・決着解決（16:38）・評価指標算出（16:48）・PITスナップショット
    （16:45/16:50）がすべて出揃った後に発火する。週次（日曜早朝）・月次の再学習/昇格ゲートも
    その日の分はここに含まれる（`plans/05_決定ログと未決事項.md` 参照）。
    """
    from backend.services.vault_report.pipeline_log_service import generate_pipeline_log_for_date

    result = asyncio.run(generate_pipeline_log_for_date())
    return result.model_dump()
