"""TrendSyncService — 収集 → 分析 → 永続化のオーケストレーションと TTL ゲート.

Market Lens `backend/services/trend/sync_service.py` から移植。変更点（🔧）:
- DB アクセスを raw sqlite `database` → SQLAlchemy async `services/db/trend_snapshot_db` に置換。
- `analyzer._mock_trends` → `analyzer.mock_trends`（公開名に）。

TTL（既定 3 時間）内は最新スナップショットを再利用し、LLM 呼び出しを抑える。
`asyncio.Lock` で二重実行を直列化する。`ensure_fresh()` は例外を握りつぶすベストエフォート
薄皮で、ピックパイプラインの実行前フックとして呼ぶ。
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timedelta
from typing import cast, get_args

from pydantic import ValidationError

from backend.models.trend_tracking import SnapshotStatus, Trend, TrendSnapshot
from backend.services.data.trend import analyzer, collector
from backend.services.db import trend_snapshot_db
from backend.services.jst_time import JST
from backend.services.llm.errors import LLMError
from backend.services.llm.registry import resolve_feature_provider

logger = logging.getLogger(__name__)

_TTL_SEC = 3 * 60 * 60
_run_lock = asyncio.Lock()

_ALLOWED_STATUS: frozenset[str] = frozenset(get_args(SnapshotStatus))


def _now() -> datetime:
    return datetime.now(JST)


def _row_int(value: object) -> int:
    return int(value) if isinstance(value, (int, float)) else 0


def _row_str(value: object) -> str:
    return str(value) if value is not None else ""


def _parse_snapshot_at(value: str) -> datetime | None:
    try:
        dt = datetime.fromisoformat(value)
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=JST)


def _coerce_status(value: str) -> SnapshotStatus:
    return cast("SnapshotStatus", value if value in _ALLOWED_STATUS else "ok")


def _snapshot_from_row(row: dict[str, object]) -> TrendSnapshot:
    raw_trends = json.loads(str(row["trends"]))
    trends: list[Trend] = []
    for item in raw_trends if isinstance(raw_trends, list) else []:
        try:
            trends.append(Trend.model_validate(item))
        except ValidationError:
            continue
    return TrendSnapshot(
        snapshot_at=_row_str(row["snapshot_at"]),
        status=_coerce_status(_row_str(row["status"])),
        model=_row_str(row["model"]),
        trends=trends,
        signal_count=_row_int(row.get("signal_count")),
        source_summary=_row_str(row.get("source_summary") or ""),
        generated_at=_row_str(row.get("created_at") or row["snapshot_at"]),
        message=None,
    )


def _is_fresh(row: dict[str, object]) -> bool:
    at = _parse_snapshot_at(str(row.get("snapshot_at") or ""))
    if at is None:
        return False
    return _now() - at < timedelta(seconds=_TTL_SEC)


async def _build_and_persist() -> TrendSnapshot:
    now_iso = _now().isoformat(timespec="seconds")
    date_key = _now().strftime("%Y%m%d")
    signals = await collector.collect_signals()
    provider = resolve_feature_provider("trend_analyzer")

    status: str
    message: str | None
    if signals.is_mock and not provider.is_configured:
        trends = analyzer.mock_trends(now_iso, date_key)
        status = "mock"
        message = "実データ・LLM プロバイダともに未設定のため、モックのトレンドを表示しています。"
    elif not provider.is_configured:
        trends = analyzer.mock_trends(now_iso, date_key)
        status = "not_configured"
        message = f"{provider.provider_id} API キーが未設定のため、モックのトレンドを表示しています。"
    else:
        try:
            trends = await analyzer.analyze(signals.headlines, signals.sector_notes)
        except LLMError as exc:
            logger.warning("トレンド同期: LLM 分析に失敗 (%s)", exc)
            return TrendSnapshot(
                snapshot_at=now_iso,
                status="llm_error",
                model=provider.model_for("trend_analyzer"),
                trends=[],
                signal_count=signals.signal_count,
                source_summary=signals.source_summary,
                generated_at=now_iso,
                message="トレンド分析に一時的に失敗しました。しばらくして再試行してください。",
            )
        status = "mock" if signals.is_mock else "ok"
        message = "収集ソースが得られずモックデータで分析しました。" if signals.is_mock else None

    if not trends:
        status = "no_signals"
        message = message or "有用なトレンドを抽出できませんでした。"

    await trend_snapshot_db.insert_trend_snapshot(
        snapshot_at=now_iso,
        status=status,
        model=provider.model_for("trend_analyzer"),
        trends=[t.model_dump() for t in trends],
        signal_count=signals.signal_count,
        source_summary=signals.source_summary,
    )
    return TrendSnapshot(
        snapshot_at=now_iso,
        status=_coerce_status(status),
        model=provider.model_for("trend_analyzer"),
        trends=trends,
        signal_count=signals.signal_count,
        source_summary=signals.source_summary,
        generated_at=now_iso,
        message=message,
    )


async def sync_trends(*, force: bool = False) -> TrendSnapshot:
    """最新スナップショットを返す（TTL 内なら再利用、そうでなければ収集 → 分析 → 永続化）."""
    async with _run_lock:
        latest = await trend_snapshot_db.get_latest_trend_snapshot()
        if latest is not None and not force and _is_fresh(latest):
            return _snapshot_from_row(latest)
        try:
            return await _build_and_persist()
        except LLMError:
            raise
        except Exception:  # noqa: BLE001 — 収集 / DB の想定外障害。既存があれば返す
            logger.warning("トレンド同期に失敗", exc_info=True)
            if latest is not None:
                return _snapshot_from_row(latest)
            raise


async def get_latest() -> TrendSnapshot | None:
    """永続化済みの最新スナップショット（無ければ None）。UI / コンテキスト用の軽い読み取り."""
    row = await trend_snapshot_db.get_latest_trend_snapshot()
    return _snapshot_from_row(row) if row is not None else None


async def ensure_fresh() -> None:
    """ピックパイプラインの実行前フック。TTL 切れなら同期する。失敗は握りつぶす."""
    try:
        latest = await trend_snapshot_db.get_latest_trend_snapshot()
        if latest is None or not _is_fresh(latest):
            await sync_trends()
    except Exception:  # noqa: BLE001 — フックの失敗が本処理を止めないようにする
        logger.warning("トレンドの ensure_fresh に失敗（本処理は続行）", exc_info=True)
