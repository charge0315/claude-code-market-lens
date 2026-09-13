"""ポートフォリオ（保有銘柄）関連の Pydantic スキーマ定義.

Market Lens `backend/models/portfolio.py` から移植（🔧）。`portfolios` テーブルは Alpha Forge の
baseline スキーマに合わせて `holding_id`（UUID 文字列 PK）/ `symbol` / `acquired_at`
（同一銘柄を複数ロットで保有できるよう `UNIQUE(symbol, acquired_at)`）を使う。
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, field_validator

PortfolioSignalAction = Literal["hold", "trim", "stop_loss", "add"]
PortfolioSignalStatus = Literal["proposed", "approved", "rejected", "executed"]


class AddHoldingRequest(BaseModel):
    model_config = ConfigDict(frozen=True)

    symbol: str
    quantity: int
    avg_cost: float  # 平均取得単価（円）
    acquired_at: str  # 取得日（YYYY-MM-DD）。同一銘柄でも取得日が異なれば別ロットとして扱う。

    @field_validator("quantity")
    @classmethod
    def quantity_positive(cls, v: int) -> int:
        if v <= 0:
            raise ValueError("株数は正の値を指定してください")
        return v

    @field_validator("avg_cost")
    @classmethod
    def avg_cost_positive(cls, v: float) -> float:
        if v <= 0:
            raise ValueError("平均取得単価は正の値を指定してください")
        return v


class UpdateHoldingRequest(BaseModel):
    model_config = ConfigDict(frozen=True)

    quantity: int
    avg_cost: float

    @field_validator("quantity")
    @classmethod
    def quantity_positive(cls, v: int) -> int:
        if v <= 0:
            raise ValueError("株数は正の値を指定してください")
        return v

    @field_validator("avg_cost")
    @classmethod
    def avg_cost_positive(cls, v: float) -> float:
        if v <= 0:
            raise ValueError("平均取得単価は正の値を指定してください")
        return v


class SellHoldingRequest(BaseModel):
    """`POST /api/portfolio/holdings/{holding_id}/sell` のリクエストボディ（🆕 P26）.

    `quantity` が保有株数と同数なら全量売却（ロット自体を削除）、それ未満なら一部売却
    （残り株数へ更新）として扱う。平均取得単価はロットの `avg_cost` をそのまま使う
    （売却時に別値を指定させると実現損益の計算根拠が崩れるため）。
    """

    model_config = ConfigDict(frozen=True)

    quantity: int
    sell_price: float
    sold_at: str  # 売却日（YYYY-MM-DD）
    note: str | None = None

    @field_validator("quantity")
    @classmethod
    def quantity_positive(cls, v: int) -> int:
        if v <= 0:
            raise ValueError("売却株数は正の値を指定してください")
        return v

    @field_validator("sell_price")
    @classmethod
    def sell_price_positive(cls, v: float) -> float:
        if v <= 0:
            raise ValueError("売却価格は正の値を指定してください")
        return v


class SellHistoryEntry(BaseModel):
    """売却履歴の1行（🆕 P26）."""

    model_config = ConfigDict(frozen=True)

    sell_id: str
    holding_id: str
    symbol: str
    company_name: str | None = None
    quantity: int
    avg_cost: float
    sell_price: float
    realized_pnl: float
    sold_at: str
    note: str | None = None


class PortfolioHolding(BaseModel):
    """リアルタイム価格で評価済みの保有銘柄（1 ロット）."""

    model_config = ConfigDict(frozen=True)

    holding_id: str
    symbol: str
    company_name: str | None = None
    sector: str | None = None
    quantity: int
    avg_cost: float
    current_price: float | None = None
    current_value: float | None = None  # quantity × current_price
    cost_basis: float  # quantity × avg_cost
    gain_loss: float | None = None  # current_value - cost_basis
    return_pct: float | None = None  # gain_loss / cost_basis
    acquired_at: str


class SectorAllocation(BaseModel):
    model_config = ConfigDict(frozen=True)

    sector: str
    value: float
    pct: float


class PortfolioSummary(BaseModel):
    model_config = ConfigDict(frozen=True)

    total_value: float
    total_cost: float
    total_gain_loss: float
    total_return_pct: float
    day_gain_loss: float | None = None  # 当日変動（前日終値が全銘柄で取得できた場合のみ）
    holdings: list[PortfolioHolding]
    sector_allocations: list[SectorAllocation]
    holding_count: int
    updated_at: str


class PortfolioSignalShadow(BaseModel):
    """AI 売買タイミング判定の Gemini（challenger）版（🆕、比較参考用）.

    Claude（公式）と同一のプロンプトを Gemini にも判定させ、`portfolio_signals` の承認・
    却下・実約定判定には一切関与しない表示専用の比較材料として記録する
    （`shadow_predictions` と同じ設計思想、CLAUDE.md「継続学習の教師信号は自分の実測値のみ」）。
    """

    model_config = ConfigDict(frozen=True)

    shadow_id: str
    signal_id: str
    challenger_version: str
    action: PortfolioSignalAction
    entry: float | None = None
    stop: float
    target: float
    confidence: float
    reasoning: str
    created_at: str


class PortfolioSignal(BaseModel):
    """保有 1 件に対する AI 売買タイミング判定（HITL 承認キュー、PF-3〜PF-5）.

    `entry` は `action="add"` のときのみ値を持つ（新規買い増し価格）。`hold`/`trim`/`stop_loss`
    は既存ポジションの更新後 stop/target のみを提案し `entry=None`。
    """

    model_config = ConfigDict(frozen=True)

    signal_id: str
    symbol: str
    evaluated_at: str
    action: PortfolioSignalAction
    entry: float | None = None
    stop: float
    target: float
    confidence: float
    rationale: str
    status: PortfolioSignalStatus
    fill_report: str | None = None  # JSON 文字列（ReportFillRequest の内容）
    # 🆕 Gemini（challenger）の同一判定（比較参考用、無ければ None）。
    gemini_shadow: PortfolioSignalShadow | None = None


class ReportFillRequest(BaseModel):
    """承認済みシグナルに対する実約定結果の報告（人間が入力、HITL）."""

    model_config = ConfigDict(frozen=True)

    executed_price: float
    executed_quantity: int
    executed_at: str  # 約定日時（ISO8601）
    note: str | None = None

    @field_validator("executed_price")
    @classmethod
    def executed_price_positive(cls, v: float) -> float:
        if v <= 0:
            raise ValueError("約定価格は正の値を指定してください")
        return v

    @field_validator("executed_quantity")
    @classmethod
    def executed_quantity_positive(cls, v: int) -> int:
        if v <= 0:
            raise ValueError("約定株数は正の値を指定してください")
        return v
