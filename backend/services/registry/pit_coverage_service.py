"""PIT（point-in-time）特徴量スナップショットの収集進捗集計（🆕 P29）.

モデルラボ「かんたん」タブの一言進捗表示・「詳細」タブの被覆率パネル向け。
`plans/03_システム設計` §3.7.4（ブートストラップ被覆率ゲート）の判定に使う
「収集済み営業日数」を、実際に学習パネルを組まずに `pit_fundamental_snapshots` /
`pit_sentiment_snapshots` の distinct 日数から直接求める軽量な近似値として提供する
（学習パネル構築はユニバース全体の価格取得を伴い重いため、進捗表示のためだけには使わない）。
"""

from __future__ import annotations

from backend.config import settings
from backend.models.registry import PitCoverageStatus, PitGroupCoverage
from backend.services.db import pit_snapshot_db
from backend.services.jst_time import today_jst
from backend.services.learning import pit_feature_service as pit_fs

# 実運用で最初のスナップショットより前になることが無い、十分に古い下限日（全履歴を拾う）。
_EPOCH = "2000-01-01"

_GROUP_LABELS: dict[str, str] = {
    pit_fs.FUNDAMENTAL_GROUP: "ファンダメンタル（Vault決算情報）",
    pit_fs.sentiment_group("keyword"): "ニュースセンチメント（キーワード判定）",
    pit_fs.sentiment_group("llm"): "ニュースセンチメント（LLM判定・shortlistのみ）",
}


async def _fundamental_days() -> int:
    dates = await pit_snapshot_db.distinct_fundamental_snapshot_dates(since=_EPOCH, until=today_jst())
    return len(dates)


async def _sentiment_days(source: str) -> int:
    rows = await pit_snapshot_db.list_sentiment_range(codes=None, since=_EPOCH, until=today_jst(), source=source)
    return len({str(r["snapshot_date"]) for r in rows})


async def build_pit_coverage_status() -> PitCoverageStatus:
    """全グループの収集進捗（収集済み営業日数・残り日数・投入準備完了フラグ）を返す."""
    min_days = settings.pit_min_coverage_days
    collected = {
        pit_fs.FUNDAMENTAL_GROUP: await _fundamental_days(),
        pit_fs.sentiment_group("keyword"): await _sentiment_days("keyword"),
        pit_fs.sentiment_group("llm"): await _sentiment_days("llm"),
    }

    groups = [
        PitGroupCoverage(
            group=group,
            label=_GROUP_LABELS[group],
            collected_days=days,
            min_coverage_days=min_days,
            remaining_days=max(0, min_days - days),
            ready=days >= min_days,
        )
        for group, days in collected.items()
    ]
    return PitCoverageStatus(features_enabled=settings.pit_features_enabled, groups=groups)
