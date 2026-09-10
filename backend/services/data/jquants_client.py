"""J-Quants API 非同期クライアント (V2).

Market Lens `backend/services/jquants_client.py` から移植（import パスのみ変更:
`services.jquants_errors` → `services.data.jquants_errors`）。

環境変数 ``JQUANTS_API_KEY`` を設定すると有効になる。未設定なら ``is_configured=False`` を
返し、呼び出し元が yfinance にフォールバックできる。V2 認証はヘッダ ``x-api-key`` に
API キーをそのまま渡す（トークン交換不要）。

耐障害性: トランスポート層（``_get``）が raw httpx 例外を型付き ``JQuantsError`` に翻訳し、
``_request_with_retry`` が指数バックオフ + フルジッタでリトライしつつ、サーキットブレーカで
持続障害時の無駄なタイムアウト待ちを遮断する。
"""

from __future__ import annotations

import asyncio
import datetime
import logging
import random
from typing import cast

import httpx
import pandas as pd
from pydantic import ValidationError

from backend.config import settings
from backend.models.jquants_raw import RawDailyBar, RawListedInfo, RawStatement
from backend.services.circuit_breaker import CircuitBreaker
from backend.services.data.jquants_errors import (
    JQuantsCircuitOpenError,
    JQuantsClientError,
    JQuantsConnectionError,
    JQuantsError,
    JQuantsResponseError,
    JQuantsServerError,
    JQuantsTimeoutError,
    to_http,
)

logger = logging.getLogger(__name__)

JQUANTS_BASE = "https://api.jquants.com/v2"

JsonDict = dict[str, object]

_TIMEOUT = httpx.Timeout(connect=5.0, read=15.0, write=5.0, pool=5.0)

_RETRYABLE_STATUS: frozenset[int] = frozenset({429, 500, 502, 503, 504})

_MAX_ATTEMPTS = 3
_BASE_DELAY_SEC = 0.5
_BACKOFF_MULTIPLIER = 2.0
_MAX_DELAY_SEC = 8.0

# _get_paginated の反復回数上限（異常な pagination_key で無限ループ・メモリ増大に陥らない安全弁）。
_MAX_PAGES = 100

_PERIOD_TO_DAYS: dict[str, int] = {
    "2w": 14,
    "1mo": 30,
    "3mo": 90,
    "6mo": 180,
    "1y": 365,
    "2y": 730,
    "5y": 1825,
    "10y": 3650,
}


def _compute_backoff(attempt: int, retry_after: float | None = None) -> float:
    """指数バックオフ + フルジッタの待機秒を返す（Retry-After 指定時はそれを優先）."""
    if retry_after is not None:
        return min(retry_after, _MAX_DELAY_SEC)
    ceiling = min(_MAX_DELAY_SEC, _BASE_DELAY_SEC * _BACKOFF_MULTIPLIER**attempt)
    return random.uniform(0.0, ceiling)  # nosec B311 — 暗号用途ではないためデフォルト乱数で十分


class JQuantsClient:
    """J-Quants API V2 の非同期シングルトンクライアント."""

    _instance: JQuantsClient | None = None
    _ready: bool = False

    def __new__(cls) -> JQuantsClient:
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._ready = False
        return cls._instance

    def __init__(self) -> None:
        if self._ready:
            return
        # open_error_factory を明示しないと汎用 CircuitOpenError が送出され、to_http() の
        # isinstance(exc, JQuantsCircuitOpenError) 分岐が効かなくなる。
        self._breaker = CircuitBreaker(open_error_factory=JQuantsCircuitOpenError)
        self._ready = True

    @property
    def _api_key(self) -> str:
        return settings.jquants_api_key

    @property
    def is_configured(self) -> bool:
        """必要な環境変数が設定されているかを返す."""
        return bool(self._api_key)

    # --- API リクエスト ---

    def _auth_headers(self) -> dict[str, str]:
        return {"x-api-key": self._api_key}

    async def _get(self, endpoint: str, params: JsonDict | None = None) -> JsonDict:
        """V2 認証済み GET を送信し、httpx 例外を型付き JQuantsError に翻訳する."""
        url = f"{JQUANTS_BASE}{endpoint}"
        try:
            async with httpx.AsyncClient(timeout=_TIMEOUT) as c:
                resp = await c.get(
                    url,
                    headers=self._auth_headers(),
                    params=cast("dict[str, str | int | float | bool | None]", params or {}),
                )
        except httpx.TimeoutException as e:
            raise JQuantsTimeoutError(endpoint) from e
        except (httpx.ConnectError, httpx.ReadError, httpx.NetworkError, httpx.RemoteProtocolError) as e:
            raise JQuantsConnectionError(endpoint) from e

        if resp.is_success:
            return cast("JsonDict", resp.json())

        status = resp.status_code
        body_text = resp.text[:500]
        logger.warning("J-Quants %s %s → %s", status, endpoint, body_text[:200])
        if status in _RETRYABLE_STATUS:
            raise JQuantsServerError(endpoint, status, resp.headers.get("Retry-After"))
        raise JQuantsClientError(endpoint, status, body=body_text)

    async def _request_with_retry(self, endpoint: str, params: JsonDict | None) -> JsonDict:
        """リトライ + サーキットブレーカでラップした GET.

        タイムアウト / 接続 / 上流 5xx はバックオフ付きでリトライし、枯渇したら送出する。
        4xx とスキーマエラーは即時 propagate。トランスポート障害のみがブレーカを開く。
        """
        self._breaker.before_request()

        last_exc: JQuantsError | None = None
        for attempt in range(_MAX_ATTEMPTS):
            try:
                result = await self._get(endpoint, params)
            except (JQuantsTimeoutError, JQuantsConnectionError, JQuantsServerError) as e:
                last_exc = e
                if attempt == _MAX_ATTEMPTS - 1:
                    break
                delay = _compute_backoff(attempt, retry_after=getattr(e, "retry_after", None))
                logger.info("J-Quants retry %d/%d after %.2fs: %s", attempt + 1, _MAX_ATTEMPTS, delay, e)
                await asyncio.sleep(delay)
            else:
                self._breaker.record_success()
                return result

        # リトライ枯渇 = 継続的なトランスポート障害としてブレーカに記録する。
        self._breaker.record_failure()
        if last_exc is None:
            raise RuntimeError("リトライループが例外なしで終了することはない")
        raise last_exc

    async def _get_paginated(
        self,
        endpoint: str,
        params: JsonDict | None = None,
        data_key: str = "data",
    ) -> list[JsonDict]:
        """ページネーションに対応した GET ヘルパー（各ページを個別にリトライする）."""
        query: JsonDict = dict(params or {})
        all_data: list[JsonDict] = []

        for _ in range(_MAX_PAGES):
            payload = await self._request_with_retry(endpoint, params=query)
            batch = payload.get(data_key, [])
            if isinstance(batch, list):
                all_data.extend(batch)
            pagination_key = payload.get("pagination_key")
            if not pagination_key:
                return all_data
            query["pagination_key"] = pagination_key

        raise JQuantsResponseError(
            f"{endpoint}: ページネーションが{_MAX_PAGES}ページを超えて終端しませんでした"
            "（上流の pagination_key が異常な可能性があります）"
        )

    # --- データ取得 ---

    @staticmethod
    def _to_date_range(period: str) -> tuple[str, str]:
        """期間文字列を (from_date, to_date) の YYYY-MM-DD 文字列に変換する."""
        today = datetime.date.today()
        days = _PERIOD_TO_DAYS.get(period, 365)
        return (
            (today - datetime.timedelta(days=days)).strftime("%Y-%m-%d"),
            today.strftime("%Y-%m-%d"),
        )

    @staticmethod
    def _to_5digit(code: str) -> str:
        """4 桁コードを J-Quants の 5 桁コード（普通株は末尾 0）に変換する."""
        c = code.strip().split(".")[0]  # .T サフィックスを除去
        return f"{c}0" if len(c) == 4 else c

    async def fetch_daily_quotes(self, code: str, period: str = "1y") -> pd.DataFrame:
        """日次株価データを取得し、yfinance 互換の DataFrame を返す.

        インフラ / 上流障害時は ``JQuantsError`` を送出（呼び出し元がフォールバック判断）。
        上流が真に空のときのみ空 DataFrame を返す。
        """
        from_date, to_date = self._to_date_range(period)
        code5 = self._to_5digit(code)

        records = await self._get_paginated(
            "/equities/bars/daily",
            params={"code": code5, "from": from_date, "to": to_date},
        )
        if not records:
            return pd.DataFrame()

        try:
            bars = [RawDailyBar.model_validate(r) for r in records]
        except ValidationError as e:
            raise JQuantsResponseError(f"日次株価のスキーマ検証に失敗しました: {code5}") from e

        # バッチガード: 全レコードで終値が欠落 → AdjC 改名などスキーマ変更の疑い。
        if all(b.adj_close is None for b in bars):
            raise JQuantsResponseError("AdjC missing — possible upstream schema change")

        df = pd.DataFrame(
            {
                "Date": [b.date for b in bars],
                "Open": [b.adj_open for b in bars],
                "High": [b.adj_high for b in bars],
                "Low": [b.adj_low for b in bars],
                "Close": [b.adj_close for b in bars],
                "Volume": [b.adj_volume for b in bars],
            }
        )
        df["Date"] = pd.to_datetime(df["Date"])
        df = df.sort_values("Date").set_index("Date")
        return df.dropna(subset=["Close"])

    async def fetch_statements(self, code: str) -> list[RawStatement]:
        """財務サマリデータを取得する（直近 20 件を開示日降順）."""
        records = await self._get_paginated("/fins/summary", params={"code": code[:4]})
        if not records:
            return []

        try:
            parsed = [RawStatement.model_validate(r) for r in records]
        except ValidationError as e:
            raise JQuantsResponseError(f"財務諸表のスキーマ検証に失敗しました: {code}") from e

        if all(s.disclosed_date is None for s in parsed):
            raise JQuantsResponseError("DiscDate missing — possible upstream schema change")

        return sorted(parsed, key=lambda s: s.disclosed_date or "", reverse=True)[:20]

    async def fetch_listed_info(self, code: str) -> RawListedInfo | None:
        """銘柄基本情報を取得する（検証済みモデル / 該当なしは None）."""
        records = await self._get_paginated("/equities/master", params={"code": code[:4]})
        if not records:
            return None
        try:
            return RawListedInfo.model_validate(records[-1])
        except ValidationError as e:
            raise JQuantsResponseError(f"銘柄基本情報のスキーマ検証に失敗しました: {code}") from e

    async def fetch_all_listed_stocks(self) -> list[JsonDict]:
        """全上場銘柄の基本情報（業種コード含む）を一括取得する（集計向け・寛容）.

        ~4000 行のうち 1 行の不正が全体を潰さないよう行単位で検証してスキップする。
        集計専用でノーフォールバックの消費者を持たないため、``JQuantsError`` は内部で
        握りつぶして空リストを返す。戻り値は dict アクセス契約を維持するため生レコードのまま返す。
        """
        try:
            records = await self._get_paginated("/equities/master")
        except JQuantsError as e:
            logger.warning("J-Quants fetch_all_listed_stocks 失敗: %s", e)
            return []

        valid: list[JsonDict] = []
        for row in records:
            try:
                RawListedInfo.model_validate(row)
            except ValidationError:
                logger.warning("上場銘柄マスタの不正行をスキップ: %s", row.get("Code"))
                continue
            valid.append(row)

        if valid and not any(("S33Nm" in row or "S17Nm" in row) for row in valid):
            logger.error("listed master sector fields absent — possible schema change")

        return valid

    async def fetch_all_daily_bars(self, date: str) -> list[JsonDict]:
        """指定日の全上場銘柄の日次四本値を一括取得する（集計向け・寛容）.

        ``/equities/bars/daily`` は ``code`` を省略し ``date`` のみ指定すると、その日の
        全上場銘柄（約 4400 件）を 1 リクエストで返す（pagination なし）。非営業日は
        200 + 空リストで返るため、呼び出し元（ranking_service）が前営業日へ遡る判断に使う。
        インフラ / 上流障害は ``JQuantsError`` を送出し、ここでは握りつぶさない
        （「非営業日で空」と「取得失敗」を混同させないため）。
        """
        return await self._get_paginated("/equities/bars/daily", params={"date": date})

    async def check_connection(self) -> dict[str, str]:
        """接続状態を確認する."""
        if not self.is_configured:
            return {"status": "not_configured", "message": "JQUANTS_API_KEY が未設定です"}
        try:
            records = await self._get_paginated("/equities/master", params={"code": "72030"})
            return {
                "status": "connected",
                "message": f"J-Quants V2 API に接続済みです（銘柄マスタ {len(records)} 件）",
            }
        except JQuantsError as e:
            _, message, _ = to_http(e)
            return {"status": "error", "message": message}


# モジュールレベルのシングルトン。
jquants = JQuantsClient()
