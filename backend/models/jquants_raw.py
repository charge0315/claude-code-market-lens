"""J-Quants V2 レスポンスの生スキーマ（省略フィールド名を alias で束縛）.

Market Lens `backend/models/jquants_raw.py` から移植（変更なし）。V2 API はフィールド名が
省略形（`AdjC` / `DiscDate` 等）で返るため alias で可読名に束縛する。`extra="ignore"` で
additive な新規フィールドは黙って許容し、critical フィールドの改名 / 欠落はクライアント層の
バッチガードで検知する。
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, field_validator

_DAILY_NUMERIC_FIELDS = ("adj_open", "adj_high", "adj_low", "adj_close", "adj_volume")

_STATEMENT_NUMERIC_FIELDS = (
    "net_sales",
    "operating_profit",
    "ordinary_profit",
    "profit",
    "eps",
    "total_assets",
    "net_assets",
)


def coerce_optional_float(value: object) -> float | None:
    """'', None, 非数値 → None。数値 / 数値文字列 → float（J-Quants は数値を文字列で返すことがある）."""
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return None
    return None


class RawDailyBar(BaseModel):
    """日次株価バー（権利調整済み）."""

    model_config = ConfigDict(frozen=True, populate_by_name=True, extra="ignore")

    date: str = Field(alias="Date")  # critical（DataFrame の index）
    adj_open: float | None = Field(default=None, alias="AdjO")
    adj_high: float | None = Field(default=None, alias="AdjH")
    adj_low: float | None = Field(default=None, alias="AdjL")
    adj_close: float | None = Field(default=None, alias="AdjC")  # critical（dropna 対象）
    adj_volume: float | None = Field(default=None, alias="AdjVo")

    @field_validator(*_DAILY_NUMERIC_FIELDS, mode="before")
    @classmethod
    def _coerce_numeric(cls, value: object) -> float | None:
        return coerce_optional_float(value)


class RawStatement(BaseModel):
    """財務サマリ（/fins/summary の 1 レコード）."""

    model_config = ConfigDict(frozen=True, populate_by_name=True, extra="ignore")

    disclosed_date: str | None = Field(default=None, alias="DiscDate")  # ソートキー
    fiscal_year_end: str | None = Field(default=None, alias="CurFYEn")
    period_type: str | None = Field(default=None, alias="CurPerType")
    net_sales: float | None = Field(default=None, alias="Sales")
    operating_profit: float | None = Field(default=None, alias="OP")
    ordinary_profit: float | None = Field(default=None, alias="OdP")
    profit: float | None = Field(default=None, alias="NP")
    eps: float | None = Field(default=None, alias="EPS")
    total_assets: float | None = Field(default=None, alias="TA")
    net_assets: float | None = Field(default=None, alias="Eq")

    @field_validator(*_STATEMENT_NUMERIC_FIELDS, mode="before")
    @classmethod
    def _coerce_numeric(cls, value: object) -> float | None:
        return coerce_optional_float(value)


class RawListedInfo(BaseModel):
    """銘柄基本情報（/equities/master の 1 レコード）.

    実際の V2 レスポンスは `CoName` / `S33Nm` 等の省略フィールド名で返る。
    """

    model_config = ConfigDict(frozen=True, populate_by_name=True, extra="ignore")

    code: str = Field(alias="Code")  # critical（銘柄識別子）
    company_name: str | None = Field(default=None, alias="CoName")
    company_name_en: str | None = Field(default=None, alias="CoNameEn")
    sector33_code: str | None = Field(default=None, alias="S33")
    sector33_name: str | None = Field(default=None, alias="S33Nm")
    sector17_code: str | None = Field(default=None, alias="S17")
    sector17_name: str | None = Field(default=None, alias="S17Nm")
