"""銘柄マスタ・株価データの共通スキーマ.

Market Lens `backend/models/schemas.py` の `TickerInfo` を移植（他のスキーマは使う
フェーズで追加する）。
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class TickerInfo(BaseModel):
    """銘柄の基本属性（コード・名称・業種）."""

    model_config = ConfigDict(frozen=True)

    code: str
    name: str
    sector: str | None = None
