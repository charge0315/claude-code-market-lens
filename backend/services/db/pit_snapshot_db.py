"""`pit_fundamental_snapshots` / `pit_sentiment_snapshots` / `pit_supply_demand_snapshots` の読み書き.

SQLAlchemy async。

`plans/03_システム設計` §1.8。1 営業日 × 1 銘柄（センチメントは source も含む）で 1 行の
append-only な point-in-time（時点整合）台帳。`(snapshot_date, code[, source])` の一意制約で
upsert する — 同一日内の再実行は上書き可能だが、過去日の行を書き換える経路はどの関数にも
持たせない（呼び出し側は常に「今日分」だけを渡す設計、`services/learning/pit_snapshot_service.py`）。
"""

from __future__ import annotations

import uuid

from sqlalchemy import text

from backend.services.db.database import get_db

_UPSERT_FUNDAMENTAL = text("""
    INSERT INTO pit_fundamental_snapshots (
        snapshot_id, snapshot_date, code, source, data_as_of,
        per_forecast, pbr, roe, equity_ratio, dividend_yield_forecast, eps_forecast, bps,
        market_cap_oku, shares_outstanding, last_earnings_date, last_earnings_type,
        sector33, sector17, scale_cat, market, extra, created_at
    ) VALUES (
        :snapshot_id, :snapshot_date, :code, :source, :data_as_of,
        :per_forecast, :pbr, :roe, :equity_ratio, :dividend_yield_forecast, :eps_forecast, :bps,
        :market_cap_oku, :shares_outstanding, :last_earnings_date, :last_earnings_type,
        :sector33, :sector17, :scale_cat, :market, :extra, :created_at
    )
    ON CONFLICT (snapshot_date, code) DO UPDATE SET
        source = excluded.source,
        data_as_of = excluded.data_as_of,
        per_forecast = excluded.per_forecast,
        pbr = excluded.pbr,
        roe = excluded.roe,
        equity_ratio = excluded.equity_ratio,
        dividend_yield_forecast = excluded.dividend_yield_forecast,
        eps_forecast = excluded.eps_forecast,
        bps = excluded.bps,
        market_cap_oku = excluded.market_cap_oku,
        shares_outstanding = excluded.shares_outstanding,
        last_earnings_date = excluded.last_earnings_date,
        last_earnings_type = excluded.last_earnings_type,
        sector33 = excluded.sector33,
        sector17 = excluded.sector17,
        scale_cat = excluded.scale_cat,
        market = excluded.market,
        extra = excluded.extra,
        created_at = excluded.created_at
    """)

_UPSERT_SENTIMENT = text("""
    INSERT INTO pit_sentiment_snapshots (
        snapshot_id, snapshot_date, code, source, news_count,
        keyword_positive, keyword_negative, keyword_score,
        llm_sentiment_label, llm_sentiment_score, llm_impact_score, llm_confidence, created_at
    ) VALUES (
        :snapshot_id, :snapshot_date, :code, :source, :news_count,
        :keyword_positive, :keyword_negative, :keyword_score,
        :llm_sentiment_label, :llm_sentiment_score, :llm_impact_score, :llm_confidence, :created_at
    )
    ON CONFLICT (snapshot_date, code, source) DO UPDATE SET
        news_count = excluded.news_count,
        keyword_positive = excluded.keyword_positive,
        keyword_negative = excluded.keyword_negative,
        keyword_score = excluded.keyword_score,
        llm_sentiment_label = excluded.llm_sentiment_label,
        llm_sentiment_score = excluded.llm_sentiment_score,
        llm_impact_score = excluded.llm_impact_score,
        llm_confidence = excluded.llm_confidence,
        created_at = excluded.created_at
    """)


async def upsert_fundamental_snapshot(
    *,
    snapshot_date: str,
    code: str,
    source: str,
    data_as_of: str | None,
    per_forecast: float | None,
    pbr: float | None,
    roe: float | None,
    equity_ratio: float | None,
    dividend_yield_forecast: float | None,
    eps_forecast: float | None,
    bps: float | None,
    market_cap_oku: float | None,
    shares_outstanding: int | None,
    last_earnings_date: str | None,
    last_earnings_type: str | None,
    sector33: str | None,
    sector17: str | None,
    scale_cat: str | None,
    market: str | None,
    extra: str | None,
    created_at: str,
) -> None:
    """ファンダメンタル PIT スナップショットを 1 行 upsert する（`(snapshot_date, code)` 一意）."""
    async with get_db() as db:
        await db.execute(
            _UPSERT_FUNDAMENTAL,
            {
                "snapshot_id": str(uuid.uuid4()),
                "snapshot_date": snapshot_date,
                "code": code,
                "source": source,
                "data_as_of": data_as_of,
                "per_forecast": per_forecast,
                "pbr": pbr,
                "roe": roe,
                "equity_ratio": equity_ratio,
                "dividend_yield_forecast": dividend_yield_forecast,
                "eps_forecast": eps_forecast,
                "bps": bps,
                "market_cap_oku": market_cap_oku,
                "shares_outstanding": shares_outstanding,
                "last_earnings_date": last_earnings_date,
                "last_earnings_type": last_earnings_type,
                "sector33": sector33,
                "sector17": sector17,
                "scale_cat": scale_cat,
                "market": market,
                "extra": extra,
                "created_at": created_at,
            },
        )


async def upsert_sentiment_snapshot(
    *,
    snapshot_date: str,
    code: str,
    source: str,
    news_count: int,
    keyword_positive: float | None = None,
    keyword_negative: float | None = None,
    keyword_score: float | None = None,
    llm_sentiment_label: str | None = None,
    llm_sentiment_score: float | None = None,
    llm_impact_score: float | None = None,
    llm_confidence: float | None = None,
    created_at: str,
) -> None:
    """センチメント PIT スナップショットを 1 行 upsert する（`(snapshot_date, code, source)` 一意）.

    `source="keyword"` は `keyword_*` 列のみ、`source="llm"` は `llm_*` 列のみを埋める想定
    （呼び出し側が使わない側は None のまま渡す）。
    """
    async with get_db() as db:
        await db.execute(
            _UPSERT_SENTIMENT,
            {
                "snapshot_id": str(uuid.uuid4()),
                "snapshot_date": snapshot_date,
                "code": code,
                "source": source,
                "news_count": news_count,
                "keyword_positive": keyword_positive,
                "keyword_negative": keyword_negative,
                "keyword_score": keyword_score,
                "llm_sentiment_label": llm_sentiment_label,
                "llm_sentiment_score": llm_sentiment_score,
                "llm_impact_score": llm_impact_score,
                "llm_confidence": llm_confidence,
                "created_at": created_at,
            },
        )


_UPSERT_SUPPLY_DEMAND = text("""
    INSERT INTO pit_supply_demand_snapshots (
        snapshot_id, snapshot_date, code, data_as_of,
        long_volume, short_volume, margin_ratio, margin_ratio_prev, created_at
    ) VALUES (
        :snapshot_id, :snapshot_date, :code, :data_as_of,
        :long_volume, :short_volume, :margin_ratio, :margin_ratio_prev, :created_at
    )
    ON CONFLICT (snapshot_date, code) DO UPDATE SET
        data_as_of = excluded.data_as_of,
        long_volume = excluded.long_volume,
        short_volume = excluded.short_volume,
        margin_ratio = excluded.margin_ratio,
        margin_ratio_prev = excluded.margin_ratio_prev,
        created_at = excluded.created_at
    """)


async def upsert_supply_demand_snapshot(
    *,
    snapshot_date: str,
    code: str,
    data_as_of: str | None,
    long_volume: float | None,
    short_volume: float | None,
    margin_ratio: float | None,
    margin_ratio_prev: float | None,
    created_at: str,
) -> None:
    """需給（週末信用取引残高）PIT スナップショットを 1 行 upsert する（`(snapshot_date, code)` 一意）.

    🆕 中長期ピック限定（`orchestrator.py` の llm_overlay ステージから fire-and-forget で呼ぶ）。
    """
    async with get_db() as db:
        await db.execute(
            _UPSERT_SUPPLY_DEMAND,
            {
                "snapshot_id": str(uuid.uuid4()),
                "snapshot_date": snapshot_date,
                "code": code,
                "data_as_of": data_as_of,
                "long_volume": long_volume,
                "short_volume": short_volume,
                "margin_ratio": margin_ratio,
                "margin_ratio_prev": margin_ratio_prev,
                "created_at": created_at,
            },
        )


async def list_fundamental_range(*, codes: list[str] | None, since: str, until: str) -> list[dict[str, object]]:
    """`[since, until]`（両端含む、`snapshot_date` 昇順）のファンダメンタル PIT 行を返す.

    `codes=None` は全銘柄（学習パネル構築時は事前にユニバースを絞って呼ぶのが前提だが、
    couverage 集計等で全体を見たい呼び出しにも対応する）。SQLite の `IN` バインドは
    パラメータ展開が必要なため、`codes` の件数ぶん `:code_N` を生成する。
    """
    clauses = ["snapshot_date >= :since", "snapshot_date <= :until"]
    params: dict[str, object] = {"since": since, "until": until}
    if codes is not None:
        code_params = {f"code_{i}": c for i, c in enumerate(codes)}
        clauses.append(f"code IN ({', '.join(f':{k}' for k in code_params)})")
        params.update(code_params)
    where = " AND ".join(clauses)
    async with get_db() as db:
        result = await db.execute(
            text(
                f"SELECT * FROM pit_fundamental_snapshots WHERE {where} ORDER BY snapshot_date ASC"  # noqa: S608  # nosec B608 - where は定数リテラルのみ・値は全てバインド
            ),
            params,
        )
        return [dict(r._mapping) for r in result]


async def list_sentiment_range(
    *, codes: list[str] | None, since: str, until: str, source: str
) -> list[dict[str, object]]:
    """`[since, until]` のセンチメント PIT 行を `source`（`"keyword"` / `"llm"`）指定で返す."""
    clauses = ["snapshot_date >= :since", "snapshot_date <= :until", "source = :source"]
    params: dict[str, object] = {"since": since, "until": until, "source": source}
    if codes is not None:
        code_params = {f"code_{i}": c for i, c in enumerate(codes)}
        clauses.append(f"code IN ({', '.join(f':{k}' for k in code_params)})")
        params.update(code_params)
    where = " AND ".join(clauses)
    async with get_db() as db:
        result = await db.execute(
            text(
                f"SELECT * FROM pit_sentiment_snapshots WHERE {where} ORDER BY snapshot_date ASC"  # noqa: S608  # nosec B608 - where は定数リテラルのみ・値は全てバインド
            ),
            params,
        )
        return [dict(r._mapping) for r in result]


async def distinct_fundamental_snapshot_dates(*, since: str, until: str) -> list[str]:
    """`[since, until]` にファンダメンタル PIT 行が存在する営業日一覧を昇順で返す（被覆率計算用）."""
    async with get_db() as db:
        result = await db.execute(
            text(
                "SELECT DISTINCT snapshot_date FROM pit_fundamental_snapshots "
                "WHERE snapshot_date >= :since AND snapshot_date <= :until ORDER BY snapshot_date ASC"
            ),
            {"since": since, "until": until},
        )
        return [str(r[0]) for r in result]
