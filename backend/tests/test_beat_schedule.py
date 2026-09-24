"""celery-beat のピック生成スケジュールを固定するテスト.

ピック生成の開始時刻は朝の note 投稿運用と直結する（2026-09-25: 手動実行で中長期0件 → 記事公開 →
07:30 の定期実行が中長期を再生成し、公開済み記事と台帳が食い違った）。記事作成前に定期実行が
終わっているよう JST 07:00 / 07:02 に前倒ししたため、意図せず戻らないよう時刻を固定する。
"""

from backend.celery_app import celery_app

# beat は UTC で評価される（JST = UTC+9、DST なし）
_JST_OFFSET_HOURS = 9


def _jst_hour_minute(entry_name: str) -> tuple[int, int]:
    schedule = celery_app.conf.beat_schedule[entry_name]["schedule"]
    (utc_hour,) = schedule.hour
    (minute,) = schedule.minute
    return (utc_hour + _JST_OFFSET_HOURS) % 24, minute


def test_mid_term_picks_run_at_0700_jst() -> None:
    assert _jst_hour_minute("run-picks-mid-term") == (7, 0)


def test_short_term_picks_run_at_0702_jst() -> None:
    assert _jst_hour_minute("run-picks-short-term") == (7, 2)


def test_morning_trend_sync_runs_before_picks() -> None:
    # 朝のピックが当日朝のトレンド文脈を使えるよう、同期（実測 ~1 分）をピック生成より前に置く
    assert _jst_hour_minute("sync-trends-morning") == (6, 45)
    assert _jst_hour_minute("sync-trends-morning") < _jst_hour_minute("run-picks-mid-term")


def test_intraday_trend_syncs_keep_their_times() -> None:
    schedule = celery_app.conf.beat_schedule["sync-trends"]["schedule"]
    jst_hours = sorted((h + _JST_OFFSET_HOURS) % 24 for h in schedule.hour)
    assert jst_hours == [10, 13, 16]
    assert schedule.minute == {13}
