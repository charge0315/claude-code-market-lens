"""日次 point-in-time スナップショット収集（🆕 P29）.

`plans/03_システム設計` §3.6 / §3.7。celery-beat から 1 日 1 回（大引け後）呼ばれ、
`pit_fundamental_snapshots` / `pit_sentiment_snapshots` へ当日分を追記する。1 銘柄の取得失敗
（Vault ノート未整備・yfinance ニュース取得エラー等）で全体を落とさないフェイルソフト設計
（`services/learning/training_data_source.py` の yfinance→J-Quants フォールバックと同じ方針）。
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime

from backend.services.data.data_fetcher import _get_ticker_master
from backend.services.db import pit_snapshot_db
from backend.services.db.portfolio_db import list_holdings
from backend.services.jst_time import JST, today_jst
from backend.services.learning.pit_provider import DEFAULT_PROVIDERS, PitFundamentalProvider
from backend.services.scoring.llm_news_sentiment_service import LlmNewsSentimentResult
from backend.services.scoring.sentiment_analyzer import get_news_sentiment

logger = logging.getLogger(__name__)

# `_candidate_pool` の horizon 別プール上限（`services/picks/pipeline.py` の `_CONFIG` と同値）。
_CANDIDATE_POOL_LIMITS: dict[str, int] = {"mid_term": 30, "short_term": 20}


async def resolve_snapshot_codes(scope: str) -> list[str]:
    """収集スコープ（`"universe"` / `"candidates"` / `"watchlist"`）を銘柄コード列へ解決する.

    `plans/03_システム設計` §3.7.7 のコスト表に対応。`"universe"` は東証全銘柄
    （ファンダメンタル収集の既定）、`"candidates"` は当日の中長期・短期候補プールの和集合、
    `"watchlist"` は現在の保有銘柄。いずれも取得失敗はフェイルソフトで空リストへ畳む
    （日次収集タスク全体を落とさない）。
    """
    if scope == "universe":
        tickers = await _get_ticker_master()
        return [t.code for t in tickers]
    if scope == "candidates":
        # 遅延 import: `services.picks.pipeline` は `services.inference.orchestrator` を
        # import し、orchestrator は本モジュールを import する（`record_llm_sentiment_snapshot`）
        # ため、モジュールトップで import すると循環 import になる。関数内 import で回避する
        # （`backend/tasks.py` の各タスクと同じ既存パターン）。
        from backend.services.picks.pipeline import _candidate_pool

        pools = await asyncio.gather(*(_candidate_pool(h, limit) for h, limit in _CANDIDATE_POOL_LIMITS.items()))
        seen: set[str] = set()
        out: list[str] = []
        for code in (c for pool in pools for c in pool):
            if code not in seen:
                seen.add(code)
                out.append(code)
        return out
    if scope == "watchlist":
        holdings = await list_holdings()
        seen = set()
        out = []
        for row in holdings:
            code = str(row["symbol"])
            if code not in seen:
                seen.add(code)
                out.append(code)
        return out
    raise ValueError(f"未知の PIT 収集スコープです: {scope}")


@dataclass(frozen=True)
class FundamentalSnapshotStats:
    """1 回分のファンダメンタル収集の結果件数."""

    attempted: int
    collected: int


@dataclass(frozen=True)
class SentimentSnapshotStats:
    """1 回分のセンチメント（keyword）収集の結果件数."""

    attempted: int
    collected: int


def _now_iso() -> str:
    return datetime.now(JST).isoformat(timespec="seconds")


async def _fetch_one(code: str, providers: tuple[PitFundamentalProvider, ...]) -> bool:
    """`providers` を優先順に試し、最初に非 None の結果を `pit_fundamental_snapshots` へ書く."""
    for provider in providers:
        try:
            record = await provider.fetch(code)
        except Exception:  # noqa: BLE001 - 1 銘柄 1 プロバイダの失敗で収集全体を止めない
            logger.warning("PIT ファンダメンタル取得に失敗しました（%s / %s）", provider.source_id, code, exc_info=True)
            continue
        if record is None:
            continue
        await pit_snapshot_db.upsert_fundamental_snapshot(
            snapshot_date=today_jst(),
            code=record.code,
            source=record.source,
            data_as_of=record.data_as_of,
            per_forecast=record.per_forecast,
            pbr=record.pbr,
            roe=record.roe,
            equity_ratio=record.equity_ratio,
            dividend_yield_forecast=record.dividend_yield_forecast,
            eps_forecast=record.eps_forecast,
            bps=record.bps,
            market_cap_oku=record.market_cap_oku,
            shares_outstanding=record.shares_outstanding,
            last_earnings_date=record.last_earnings_date,
            last_earnings_type=record.last_earnings_type,
            sector33=record.sector33,
            sector17=record.sector17,
            scale_cat=record.scale_cat,
            market=record.market,
            extra=None,
            created_at=_now_iso(),
        )
        return True
    return False


async def collect_fundamental_snapshots(
    codes: list[str], *, providers: tuple[PitFundamentalProvider, ...] = DEFAULT_PROVIDERS
) -> FundamentalSnapshotStats:
    """指定コード群について当日分のファンダメンタル PIT スナップショットを収集する（全ユニバース想定）."""
    collected = 0
    for code in codes:
        if await _fetch_one(code, providers):
            collected += 1
    return FundamentalSnapshotStats(attempted=len(codes), collected=collected)


async def collect_sentiment_snapshots_keyword(codes: list[str]) -> SentimentSnapshotStats:
    """指定コード群について当日分の keyword センチメント PIT スナップショットを収集する.

    `scoring/sentiment_analyzer.get_news_sentiment` はニュース 0 件でも
    `average_score=0.5`（中立）付きの結果を返すため、`total>0` の銘柄のみ「情報あり」として
    書き込む（`news_count=0` の行も明示的に残し、「ニュースが無かった」ことも情報として記録する）。
    """
    collected = 0
    snapshot_date = today_jst()
    for code in codes:
        try:
            summary = get_news_sentiment(code)
        except Exception:  # noqa: BLE001 - 1 銘柄の失敗で収集全体を止めない
            logger.warning("PIT keyword センチメント取得に失敗しました（%s）", code, exc_info=True)
            continue
        await pit_snapshot_db.upsert_sentiment_snapshot(
            snapshot_date=snapshot_date,
            code=code,
            source="keyword",
            news_count=summary["total"],
            keyword_positive=float(summary["positive"]),
            keyword_negative=float(summary["negative"]),
            keyword_score=summary["average_score"] if summary["total"] > 0 else None,
            created_at=_now_iso(),
        )
        if summary["total"] > 0:
            collected += 1
    return SentimentSnapshotStats(attempted=len(codes), collected=collected)


async def record_supply_demand_snapshot(code: str, data: dict[str, object]) -> None:
    """ピック生成の一部として既に取得済みの週末信用取引残高を PIT 台帳へ記録する（🆕 中長期限定）.

    `orchestrator.py` の llm_overlay ステージから fire-and-forget で呼ばれる想定（追加の
    J-Quants 呼び出しは発生しない）。失敗してもピック生成本体には一切影響させない
    （フェイルソフト、`record_llm_sentiment_snapshot` と同じ方針）。
    """

    def _as_float(key: str) -> float | None:
        value = data.get(key)
        return float(value) if isinstance(value, (int, float)) else None

    as_of = data.get("as_of")
    try:
        await pit_snapshot_db.upsert_supply_demand_snapshot(
            snapshot_date=today_jst(),
            code=code,
            data_as_of=str(as_of) if as_of is not None else None,
            long_volume=_as_float("long_volume"),
            short_volume=_as_float("short_volume"),
            margin_ratio=_as_float("margin_ratio"),
            margin_ratio_prev=_as_float("margin_ratio_prev"),
            created_at=_now_iso(),
        )
    except Exception:  # noqa: BLE001 - PIT 記録の失敗でピック生成本体を止めない
        logger.warning("PIT 需給スナップショットの記録に失敗しました（%s）", code, exc_info=True)


async def record_earnings_surprise_snapshot(code: str, data: dict[str, object]) -> None:
    """ピック生成の一部として既に取得済みの決算サプライズ・予想修正モメンタムを PIT 台帳へ記録する.

    🆕 短期・中長期の両方が対象（`orchestrator.py` の llm_overlay ステージから fire-and-forget で
    呼ばれる想定、追加の J-Quants 呼び出しは発生しない）。失敗してもピック生成本体には一切
    影響させない（フェイルソフト、`record_supply_demand_snapshot` と同じ方針）。主指標（営業利益）
    のみ列化し、他指標の内訳は呼び出し元が `feature_snapshot` へ別途残す。
    """

    def _metric_rate(metrics: object, key: str, rate_field: str) -> float | None:
        if not isinstance(metrics, dict):
            return None
        metric = metrics.get(key)
        if not isinstance(metric, dict):
            return None
        value = metric.get(rate_field)
        return float(value) if isinstance(value, (int, float)) else None

    def _revision_classification(metrics: object) -> str | None:
        if not isinstance(metrics, dict):
            return None
        metric = metrics.get("forecast_operating_profit")
        if not isinstance(metric, dict):
            return None
        classification = metric.get("classification")
        return str(classification) if classification is not None else None

    as_of = data.get("as_of")
    try:
        await pit_snapshot_db.upsert_earnings_surprise_snapshot(
            snapshot_date=today_jst(),
            code=code,
            data_as_of=str(as_of) if as_of is not None else None,
            fiscal_year_end=str(data["fiscal_year_end"]) if data.get("fiscal_year_end") is not None else None,
            period_type=str(data["period_type"]) if data.get("period_type") is not None else None,
            surprise_op_rate=_metric_rate(data.get("surprise"), "operating_profit", "surprise_rate"),
            revision_op_rate=_metric_rate(data.get("revision"), "forecast_operating_profit", "revision_rate"),
            revision_classification=_revision_classification(data.get("revision")),
            created_at=_now_iso(),
        )
    except Exception:  # noqa: BLE001 - PIT 記録の失敗でピック生成本体を止めない
        logger.warning("PIT 決算サプライズスナップショットの記録に失敗しました（%s）", code, exc_info=True)


async def record_llm_sentiment_snapshot(code: str, result: LlmNewsSentimentResult) -> None:
    """ピック生成の一部として既に取得済みの LLM ニュースセンチメント判定を PIT 台帳へ記録する.

    `orchestrator.py` の llm_overlay ステージから fire-and-forget で呼ばれる想定
    （追加 LLM 呼び出しは発生しない、§3.7.7「センチメント `llm` = shortlist の副産物記録」）。
    失敗してもピック生成本体には一切影響させない（フェイルソフト）。`reasoning`（自由記述）は
    引数として受け取らない — enum/number のみを転送する `llm_news_sentiment_service` の境界を
    呼び出し側の型シグネチャでも強制する。
    """
    try:
        await pit_snapshot_db.upsert_sentiment_snapshot(
            snapshot_date=today_jst(),
            code=code,
            source="llm",
            news_count=result.news_count,
            llm_sentiment_label=result.sentiment_label,
            llm_sentiment_score=result.sentiment_score,
            llm_impact_score=result.impact_score,
            llm_confidence=result.confidence,
            created_at=_now_iso(),
        )
    except Exception:  # noqa: BLE001 - PIT 記録の失敗でピック生成本体を止めない
        logger.warning("PIT LLM センチメントの記録に失敗しました（%s）", code, exc_info=True)
