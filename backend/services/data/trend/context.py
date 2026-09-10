"""ピックパイプラインの LLM プロンプトへ渡す、最新トレンドの定量コンテキスト整形.

Market Lens `backend/services/trend/context.py` から移植（変更なし）。
スナップショットが無い・空のときは None を返す（プロンプトへ何も足さない）。
トレンドは frontmatter / 構造化フィールド由来（LLM で構造化済み）であり、外部本文は含まない。
"""

from __future__ import annotations

from backend.models.trend_tracking import Trend
from backend.services.data.trend import sync_service

_DEFAULT_LIMIT = 5


def _line(trend: Trend) -> str:
    codes = "、".join(rt.ticker for rt in trend.related_tickers[:6]) or "—"
    return (
        f"- {trend.theme_name}（{trend.lifecycle_stage} / {trend.impact_horizon}）"
        f" momentum {trend.momentum_score:.0f}, sentiment {trend.sentiment_score:+.2f}"
        f" / 関連: {codes}"
        f" / {trend.summary}"
    )


def render_trends(trends: list[Trend], *, limit: int = _DEFAULT_LIMIT) -> str | None:
    """トレンド一覧を短い日本語ブロックへ整形する（momentum 降順、上位 limit 件）."""
    if not trends:
        return None
    ordered = sorted(trends, key=lambda t: t.momentum_score, reverse=True)[:limit]
    body = "\n".join(_line(t) for t in ordered)
    return "## 直近の市場トレンド（参考情報。momentum 0-100 / sentiment -1〜+1）\n" + body


async def render_trend_context(*, limit: int = _DEFAULT_LIMIT) -> str | None:
    """永続化済みの最新スナップショットからトレンドコンテキストを整形する（無ければ None）."""
    snapshot = await sync_service.get_latest()
    if snapshot is None:
        return None
    return render_trends(list(snapshot.trends), limit=limit)
