"""銘柄ピック（予測台帳エントリ）のスキーマ.

`plans/03_システム設計` §1.1（`prediction_ledger`）に対応。中長期 / 短期の両系統が
同じ形で台帳化される（CL-1）。
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict

HorizonType = Literal["mid_term", "short_term"]
Direction = Literal["bullish", "bearish", "neutral"]
ConfidenceBucket = Literal["high", "mid", "low"]


class SubScores(BaseModel):
    """4 分析のサブスコア（各 0〜100）."""

    model_config = ConfigDict(frozen=True)

    technical: float
    trend: float
    fundamental: float
    sentiment: float


class LedgerEntry(BaseModel):
    """予測台帳の 1 行（予測時点で確定していた情報だけで構成する）."""

    model_config = ConfigDict(frozen=True)

    pick_id: str
    run_id: str
    issued_at: str  # ISO8601 JST
    horizon_type: HorizonType
    symbol: str  # 4 桁コード
    direction: Direction
    entry: float
    stop: float
    target: float
    sub_scores: SubScores
    composite_score: float
    concordance: float
    confidence_raw: float
    confidence: float
    confidence_bucket: ConfidenceBucket
    feature_snapshot: dict[str, object]
    rationale_struct: dict[str, object]
    rationale_text: str
    model_version: str
    source_contributions: dict[str, object]
    is_shadow: bool = False
    created_at: str


class PickSummary(BaseModel):
    """API 応答用のピック要約（`feature_snapshot` は含めない）."""

    model_config = ConfigDict(frozen=True)

    pick_id: str
    issued_at: str
    horizon_type: HorizonType
    symbol: str
    company_name: str | None = None
    direction: Direction
    entry: float
    stop: float
    target: float
    composite_score: float
    concordance: float
    confidence: float
    confidence_bucket: ConfidenceBucket
    rationale_text: str
    model_version: str
    source_contributions: dict[str, object]


class ShadowPredictionSummary(BaseModel):
    """`shadow_predictions` の1行分（🆕 P12: Gemini 等 challenger LLM の比較用判定）.

    公式パイプライン（Anthropic）とは独立した表示専用の判定であり、昇格・確度較正には関与しない。
    """

    model_config = ConfigDict(frozen=True)

    shadow_id: str
    challenger_version: str
    direction: Direction
    entry: float
    stop: float
    target: float
    confidence: float
    reasoning: str | None = None
    risk_factors: list[str] = []
    holding_period_days: int | None = None
    issued_at: str


class PickDetailResponse(BaseModel):
    """`GET /api/picks/{pick_id}` の応答（`feature_snapshot` を除いた台帳行 + 表示用銘柄名）.

    以前は `ApiResponse[dict]` で台帳の生 dict をそのまま返しており、`rationale_struct`
    （LLM リスク要因・保有期間）・`source_contributions`（情報源別寄与度）・銘柄名は
    フロント側で未使用のまま埋もれていた。ピック詳細ポップアップ（🆕）でこれらを表示する
    ため、`sub_score_*` を `SubScores` へまとめ、`company_name` を追加した明示的な型へ
    整理した。
    """

    model_config = ConfigDict(frozen=True)

    pick_id: str
    run_id: str
    issued_at: str
    horizon_type: HorizonType
    symbol: str
    company_name: str | None = None
    direction: Direction
    entry: float
    stop: float
    target: float
    sub_scores: SubScores
    composite_score: float
    concordance: float
    confidence_raw: float
    confidence: float
    confidence_bucket: ConfidenceBucket
    rationale_struct: dict[str, object]
    rationale_text: str
    model_version: str
    source_contributions: dict[str, object]
    created_at: str
    shadow_predictions: list[ShadowPredictionSummary] = []


class RejectedPick(BaseModel):
    """最終ピックから外れた候補とその理由."""

    model_config = ConfigDict(frozen=True)

    symbol: str
    status: Literal[
        "rejected_inconsistent",  # 3 値の内部矛盾（サーバ側検証で却下）
        "rejected_hard_excluded",  # ハード除外（E1〜E3）
        "rejected_low_confidence",  # 確度フロア未満
        "llm_error",  # LLM 呼び出し失敗
        "all_failed",  # 弱相場で LLM が全件 should_include=false
    ]
    reason: str


class PickRunResult(BaseModel):
    """1 回のピック実行の結果（中長期 or 短期）."""

    model_config = ConfigDict(frozen=True)

    run_id: str
    horizon_type: HorizonType
    issued_at: str
    status: Literal["ok", "empty", "not_configured", "error"]
    picks: list[PickSummary]
    rejected: list[RejectedPick]
    message: str | None = None
