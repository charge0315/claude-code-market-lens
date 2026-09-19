"""全銘柄一覧＋業種＋出来高の取得（🆕 学習対象設定のカスタムリスト選択ダイアログ用）.

`ranking_service.resolve_latest_available()`（24 時間 TTL キャッシュ済み）を再利用し、
出来高専用の追加キャッシュや重いバッチ処理は持たない。J-Quants 未設定/取得失敗時は
`volume=None` のまま返す（フロントは出来高ソートを無効化表示にする）。
"""

from __future__ import annotations

import logging
from typing import Literal

from pydantic import BaseModel, ConfigDict

from backend.models.jquants_raw import coerce_optional_float
from backend.services.data import ranking_service
from backend.services.data.data_fetcher import _get_ticker_master, _to_4digit_code
from backend.services.data.jquants_client import jquants
from backend.services.data.jquants_errors import JQuantsError
from backend.services.db import training_target_db

logger = logging.getLogger(__name__)

TickerUniverseSort = Literal["code_asc", "volume_desc", "volume_asc"]


class TickerUniverseEntry(BaseModel):
    """カスタムリスト選択ダイアログ用の銘柄 1 件分（コード・名称・業種・直近出来高）."""

    model_config = ConfigDict(frozen=True)

    code: str
    name: str
    sector: str | None
    volume: float | None
    in_custom_list: bool


async def _get_latest_volume_map() -> dict[str, float]:
    """直近取引日の銘柄コード（4 桁）→出来高の対応表を返す（J-Quants 未設定/失敗時は空 dict）."""
    if not jquants.is_configured:
        return {}
    try:
        _, bars = await ranking_service.resolve_latest_available()
    except JQuantsError:
        logger.warning("出来高一覧の取得に失敗したため volume=None で返します", exc_info=True)
        return {}

    volume_by_code: dict[str, float] = {}
    for bar in bars:
        code = str(bar.get("Code") or "")
        volume = coerce_optional_float(bar.get("AdjVo"))
        if not code or volume is None:
            continue
        volume_by_code[_to_4digit_code(code)] = volume
    return volume_by_code


async def list_ticker_universe(
    *, sector: str | None = None, sort: TickerUniverseSort = "code_asc", q: str | None = None
) -> list[TickerUniverseEntry]:
    """業種フィルタ・出来高ソート・部分一致検索付きの全銘柄一覧を返す（カスタムリスト編集用）."""
    tickers = await _get_ticker_master()
    custom = set(await training_target_db.list_custom_tickers())
    volume_by_code = await _get_latest_volume_map()
    query = (q or "").strip().lower()

    entries = [
        TickerUniverseEntry(
            code=t.code,
            name=t.name,
            sector=t.sector,
            volume=volume_by_code.get(t.code),
            in_custom_list=t.code in custom,
        )
        for t in tickers
        if (sector is None or t.sector == sector) and (not query or query in t.name.lower() or query in t.code.lower())
    ]

    if sort == "volume_desc":
        entries.sort(key=lambda e: e.volume if e.volume is not None else -1.0, reverse=True)
    elif sort == "volume_asc":
        entries.sort(key=lambda e: e.volume if e.volume is not None else float("inf"))
    else:
        entries.sort(key=lambda e: e.code)
    return entries
