"""週次学習差分サマリ（🆕、`GET /api/eval/weekly-learning`）.

Market Lens の `improvement_*`（EVO ループ: コード変更の自動提案 → 実装 → 効果測定 →
kept/reverted 判定、`git revert` は人間が行う前提の半自動パッチシステム）は、CLAUDE.md の
自律運用方針「設定・コードの自動適用はしない」と相容れず、また Alpha Forge の継続学習ループ
（モデル再学習・昇格ゲート・ドリフト検知のみで、コード自体は変更しない）とは目的が異なるため
移植しない。代わりに、既に存在する継続学習アーティファクト（`eval_snapshots` /
`model_promotions` / `drift_snapshots`）から「直近1週間で何が変わったか」を人間向けに
ロールアップするだけの、読み取り専用の要約を新規実装する。
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Final

from backend.services.db import eval_db, model_registry_db
from backend.services.db.drift_db import list_drift_snapshots
from backend.services.jst_time import JST

_WINDOW_DAYS: Final[int] = 7
_TRACKED_METRICS: Final[tuple[str, ...]] = ("win_rate", "ic", "brier", "sharpe", "avg_r_multiple")
_TRACKED_SCOPES: Final[tuple[str, ...]] = ("mid_term", "short_term", "combined")


def _f(value: object) -> float | None:
    return float(value) if isinstance(value, (int, float)) else None


async def _metric_delta(scope: str, metric: str, cutoff: str) -> dict[str, object] | None:
    """指定 scope/metric の時系列から、cutoff 以前の直近値と最新値の差分を返す（無ければ None）."""
    rows = await eval_db.list_eval_snapshots(scope=scope, metric_name=metric, limit=1000)
    if not rows:
        return None
    latest = rows[-1]
    before = next((r for r in reversed(rows) if str(r.get("computed_at", "")) <= cutoff), rows[0])
    latest_v = _f(latest.get("metric_value"))
    before_v = _f(before.get("metric_value"))
    if latest_v is None or before_v is None:
        return None
    return {
        "scope": scope,
        "metric": metric,
        "before": round(before_v, 4),
        "after": round(latest_v, 4),
        "delta": round(latest_v - before_v, 4),
        "before_at": before.get("computed_at"),
        "after_at": latest.get("computed_at"),
    }


async def build_weekly_learning_summary(
    *, window_days: int = _WINDOW_DAYS, now: datetime | None = None
) -> dict[str, object]:
    """直近 `window_days` 日の評価指標差分・昇格判定・ドリフト検知をロールアップして返す.

    `now` はテスト用の基準時刻差し替え（省略時は現在時刻、JST）。
    """
    now = now or datetime.now(JST)
    cutoff = (now - timedelta(days=window_days)).isoformat(timespec="seconds")

    metric_deltas: list[dict[str, object]] = []
    for scope in _TRACKED_SCOPES:
        for metric in _TRACKED_METRICS:
            delta = await _metric_delta(scope, metric, cutoff)
            if delta is not None:
                metric_deltas.append(delta)

    all_promotions = await model_registry_db.list_promotions(limit=200)
    recent_promotions = [p for p in all_promotions if str(p.get("evaluated_at", "")) >= cutoff]

    all_drift = await list_drift_snapshots(limit=1000)
    recent_drift_flags = [d for d in all_drift if str(d.get("computed_at", "")) >= cutoff and d.get("drift_flag")]

    return {
        "window_days": window_days,
        "as_of": now.isoformat(timespec="seconds"),
        "metric_deltas": metric_deltas,
        "recent_promotions": recent_promotions,
        "recent_drift_flags": recent_drift_flags,
    }
