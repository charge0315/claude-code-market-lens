"""Celery アプリケーションインスタンス.

学習・決着バッチ・トレンド同期・通知監視・ドリフト検知をプロセス外で回すための基盤。
Market Lens `backend/celery_app.py` の設計を踏襲する:

- Windows では prefork pool が使えないため、ワーカーは `--pool=solo` で起動する:
    .venv/Scripts/celery.exe -A backend.celery_app worker --pool=solo --loglevel=info
- beat スケジュールは UTC 固定で評価されるため、JST 時刻は UTC へ換算して書く（JST は DST なし）。
- Redis は別途起動が必要（`docker run -p 6379:6379 redis` 等）。DB 番号は Alpha Forge 専用。

P1 時点では beat スケジュールは枠のみ（タスク本体は各フェーズで実装）。
"""

from pathlib import Path

from celery import Celery
from celery.schedules import crontab
from dotenv import load_dotenv

# celery 単独プロセス起動時は backend/main.py の load_dotenv() が走らないため、ここで明示的に読む。
load_dotenv(Path(__file__).resolve().parent.parent / ".env")

from backend.config import settings  # noqa: E402

RESULT_EXPIRES_SECONDS = 60 * 60

DEFAULT_QUEUE = "celery"
INTERACTIVE_QUEUE = "interactive"

celery_app = Celery(
    "alpha_forge",
    broker=settings.celery_broker_url,
    backend=settings.celery_result_backend,
    include=["backend.tasks"],
)

# beat スケジュール。時刻は UTC 固定で評価されるため JST は UTC へ換算して書く（JST は DST なし）。
# 方針（`plans/03_システム設計.md` §3.6）: ピック生成は寄り付き（JST 09:00）前に完了 /
# 決着・評価は夜間 / トレンド同期 1 日 4 回。保有監視・フル再学習・昇格ゲートは P5/P7 で追加する。
#
# ピック生成開始時刻（07:30 JST）の根拠: 2026-09-17 実測で run_picks_task(mid_term) 単体が
# 約23分28秒かかった（全銘柄への yfinance 価格取得 + LLM 提案生成が直列）。worker は
# --pool=solo で直列実行のため mid_term → short_term は完全に順番待ちになり、2 分ずらしは
# 二重占有回避の効果を持たない。合計 ~50 分を見込んでも寄り付き 09:00 に間に合うよう、
# 安全マージンを確保する。さらに note下書き（Obsidian/SingleHTML 出力込み、ユーザー指示）の
# LLM生成に時間を要するため、従来の 07:40 から 07:30 へ前倒しし、朝の手動投稿ワークフロー
# （Obsidianノートを確認して note.com へ貼り付け）に十分な余裕を持たせる。
# 🔧 2026-09-25 さらに 07:00 へ前倒し: 手動実行で中長期が0件（全件却下）だった日に記事を公開した後、
# 07:30 の定期実行が「本日分なし」と判定して中長期を再生成し、公開済み記事と台帳が食い違った。
# 記事作成（07:00 台）より前に定期実行を終わらせ、記事は定期実行の結果を元に書く運用にする。
_BEAT_SCHEDULE: dict[str, dict[str, object]] = {
    "run-picks-mid-term": {
        "task": "backend.tasks.run_picks_task",
        "args": ("mid_term",),
        "schedule": crontab(hour=22, minute=0),  # JST 07:00（寄り付き前、記事作成より前）
    },
    "run-picks-short-term": {
        "task": "backend.tasks.run_picks_task",
        "args": ("short_term",),
        "schedule": crontab(hour=22, minute=2),  # JST 07:02（solo worker で直列実行のため実質は順番待ち）
    },
    # 🆕 P29: PIT（point-in-time）特徴量スナップショット収集。大引け後・当日分の frontmatter/
    # ニュースが出揃うタイミング（`plans/03_システム設計` §3.6）。決着解決・評価バッチとは
    # 独立したデータ（今日時点の特徴量を記録するだけで、決着解決は使わない）のため実行順の
    # 依存はない。
    "collect-pit-fundamental-snapshot": {
        "task": "backend.tasks.collect_pit_fundamental_snapshot_task",
        "schedule": crontab(hour=7, minute=45),  # JST 16:45
    },
    "collect-pit-sentiment-snapshot": {
        "task": "backend.tasks.collect_pit_sentiment_snapshot_task",
        "schedule": crontab(hour=7, minute=50),  # JST 16:50
    },
    "resolve-pick-outcomes": {
        "task": "backend.tasks.resolve_pick_outcomes_task",
        "schedule": crontab(hour=7, minute=38),  # JST 16:38（大引け後）
    },
    "update-eval-metrics": {
        "task": "backend.tasks.update_eval_metrics_task",
        "schedule": crontab(hour=7, minute=48),  # JST 16:48（決着後）
    },
    # 🔧 2026-09-25 朝の同期のみ 07:13 → 06:45 へ分離・前倒し: ピック生成を 07:00 へ前倒ししたため、
    # 旧時刻のままだと朝のピックが前日 16:13 同期分のトレンド文脈を使ってしまう（同期の実測は ~1 分）。
    "sync-trends-morning": {
        "task": "backend.tasks.sync_trends_task",
        "schedule": crontab(hour=21, minute=45),  # JST 06:45（ピック生成 07:00 の前）
    },
    "sync-trends": {
        "task": "backend.tasks.sync_trends_task",
        "schedule": crontab(hour="1,4,7", minute=13),  # JST 10:13 / 13:13 / 16:13
    },
    "run-drift-check": {
        "task": "backend.tasks.run_drift_check_task",
        "schedule": crontab(hour=18, minute=30, day_of_week="sun"),  # JST 日曜 03:30（深夜・週次）
    },
    "run-promotion-evaluation": {
        "task": "backend.tasks.run_promotion_evaluation_task",
        "schedule": crontab(hour=18, minute=45, day_of_week="sun"),  # JST 日曜 03:45（ドリフト検知の後）
    },
    "run-pool-training": {
        "task": "backend.tasks.run_pool_training_task",
        # JST 毎月1日 04:00（月次。J-Quants 一括バー呼び出しが重いため週次より粗い頻度にする）。
        "schedule": crontab(hour=19, minute=0, day_of_month=1),
    },
    # 🆕 P29: ソースアブレーション評価。crontab は「N ヶ月ごと」を直接表現できないため月次発火
    # し、四半期開始月（1/4/7/10）以外はタスク内部で skip する（`run_pool_training` の直後、
    # 同じ月初のタイミングに揃える）。
    "run-source-ablation": {
        "task": "backend.tasks.run_source_ablation_task",
        "schedule": crontab(hour=19, minute=30, day_of_month=1),
    },
    "run-portfolio-monitor": {
        "task": "backend.tasks.run_portfolio_monitor_task",
        # 5分おき常時発火。立会時間外（JST 平日 9:00-15:30 外）はタスク内部で軽い早期 return
        # （`run_signal_scan_task` 等、既存の場中限定タスクと同じ idiom）。
        "schedule": crontab(minute="*/5"),
    },
    "run-eod-review": {
        "task": "backend.tasks.run_eod_review_task",
        "schedule": crontab(hour=7, minute=31),  # JST 16:31（大引け後）
    },
    "run-daily-note-draft": {
        "task": "backend.tasks.run_daily_note_draft_task",
        # JST 08:05（ピック生成 07:00/07:02 開始・実測合計 ~25分から十分な余裕を見た開始時刻）。
        # 生成に成功すると同じタスク内で Obsidian(.md)/SingleHTML の書き出しも行う
        # （`services/notes/note_export_service.py`、ユーザー指示: 毎朝手動でnote.comへ貼り付ける
        # ワークフロー向け）。
        "schedule": crontab(hour=23, minute=5),
    },
    "generate-vault-report": {
        "task": "backend.tasks.generate_vault_report_task",
        # JST 08:15（note下書き生成の後、同じ台帳データから個人用アーカイブを作る）。
        "schedule": crontab(hour=23, minute=15),
    },
    # 🆕 P30: 日次パイプラインログ。その日のピック生成（07:00〜）・決着解決（16:38）・
    # 評価指標算出（16:48）・PITスナップショット（16:45/16:50）が出揃った後に発火する。
    "generate-pipeline-log": {
        "task": "backend.tasks.generate_pipeline_log_task",
        "schedule": crontab(hour=8, minute=0),  # JST 17:00
    },
    # 銘柄別モデル日次学習バッチ（P9）。xgboost/random_forest は5分おき常時発火
    # （run-portfolio-monitor と同じ間隔、`per_ticker_training_service` 内部の当日上限・
    # 時間予算で1firingあたりの負荷を抑える）。lstm/transformer は torch 学習で重いため
    # 1時間おきとし、xgboost/random_forest 系や互いの firing とずれるよう分単位でずらす。
    "run-xgboost-training-batch": {
        "task": "backend.tasks.run_xgboost_training_batch_task",
        "schedule": crontab(minute="1-59/5"),
    },
    "run-random-forest-training-batch": {
        "task": "backend.tasks.run_random_forest_training_batch_task",
        "schedule": crontab(minute="3-59/5"),
    },
    "run-lstm-training-batch": {
        "task": "backend.tasks.run_lstm_training_batch_task",
        "schedule": crontab(minute=20),
    },
    "run-transformer-training-batch": {
        "task": "backend.tasks.run_transformer_training_batch_task",
        "schedule": crontab(minute=50),
    },
}

celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    result_expires=RESULT_EXPIRES_SECONDS,
    task_track_started=True,
    timezone="UTC",
    enable_utc=True,
    beat_schedule=_BEAT_SCHEDULE,
    task_default_queue=DEFAULT_QUEUE,
)
