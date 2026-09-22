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
    "forecast_net_sales",
    "forecast_operating_profit",
    "forecast_ordinary_profit",
    "forecast_profit",
    "forecast_eps",
)

_MARGIN_INTEREST_NUMERIC_FIELDS = (
    "short_volume",
    "long_volume",
    "short_negotiable_volume",
    "long_negotiable_volume",
    "short_standardized_volume",
    "long_standardized_volume",
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
    """財務サマリ（/fins/summary の 1 レコード）.

    🆕 決算サプライズ・予想修正モメンタム軸向けに、当期通期の会社予想フィールド
    （`FSales`/`FOP`/`FOdP`/`FNP`/`FEPS`）を追加（2026-09-22、`code=72030` で実 API 呼び出し
    検証済み）。四半期決算のたびにこの通期予想が更新されるため、連続する開示間の差分で
    予想修正の方向を検出できる。次期予想（`NxFSales` 等、FY 決算時のみ）・上期累計予想
    （`FSales2Q` 等）は v1 では扱わない（`services/scoring/earnings_surprise_analyzer.py` 参照）。
    """

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
    # 🆕 当期通期の会社予想（開示時点のもの。四半期を追うごとに更新される）。
    forecast_net_sales: float | None = Field(default=None, alias="FSales")
    forecast_operating_profit: float | None = Field(default=None, alias="FOP")
    forecast_ordinary_profit: float | None = Field(default=None, alias="FOdP")
    forecast_profit: float | None = Field(default=None, alias="FNP")
    forecast_eps: float | None = Field(default=None, alias="FEPS")

    @field_validator(*_STATEMENT_NUMERIC_FIELDS, mode="before")
    @classmethod
    def _coerce_numeric(cls, value: object) -> float | None:
        return coerce_optional_float(value)


class RawWeeklyMarginInterest(BaseModel):
    """週末信用取引残高（/markets/margin-interest の 1 レコード、銘柄 × 週）.

    実 API レスポンスで確認済みのフィールド名（2026-09-22、`code=72030` で実呼び出し検証済み）。
    ドキュメント（gitbook）記載の `LongMarginOutstanding` 等の英語フルネームとは異なり、
    既存の `AdjC` / `DiscDate` と同じ省略形（`ShrtVol` 等）で返る。
    """

    model_config = ConfigDict(frozen=True, populate_by_name=True, extra="ignore")

    date: str = Field(alias="Date")  # critical（週次ソートキー）
    code: str = Field(alias="Code")  # critical（銘柄識別子）
    short_volume: float | None = Field(default=None, alias="ShrtVol")  # 総信用売り残（株数）
    long_volume: float | None = Field(default=None, alias="LongVol")  # 総信用買い残（株数）
    short_negotiable_volume: float | None = Field(default=None, alias="ShrtNegVol")  # 一般信用売り残
    long_negotiable_volume: float | None = Field(default=None, alias="LongNegVol")  # 一般信用買い残
    short_standardized_volume: float | None = Field(default=None, alias="ShrtStdVol")  # 制度信用売り残
    long_standardized_volume: float | None = Field(default=None, alias="LongStdVol")  # 制度信用買い残
    issue_type: str | None = Field(default=None, alias="IssType")  # 1:信用銘柄 / 2:貸借銘柄 / 3:その他

    @field_validator(*_MARGIN_INTEREST_NUMERIC_FIELDS, mode="before")
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
