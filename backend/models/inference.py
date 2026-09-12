"""AI 推論トレース（P6, VZ-6 / N4）の型定義.

`plans/03_システム設計` §1.6。Market Lens にはこの機能が存在しない（🆕 Alpha Forge 独自）。

`STAGE_ORDER` は同 §3.1 のステージ名を挙げた順（collect→subscore→llm_overlay→synthesis→
bracket→verify）と異なる（🔧）。実際のパイプライン（`services/picks/pipeline.py`）は
LLM プロンプトに recommender の合成結果（synthesis 相当）を埋め込むため、synthesis は
llm_overlay より **前** に実行される。本モジュールは §3.1 の名前一覧は保ちつつ、実際に
テスト済みで動いている実行順（collect→subscore→synthesis→llm_overlay→bracket→verify）を
`STAGE_ORDER`（= `stage_seq` の割当順）として採用する。
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict

from backend.models.pick import LedgerEntry, RejectedPick

StageName = Literal["collect", "subscore", "synthesis", "llm_overlay", "bracket", "verify"]
StageStatus = Literal["pending", "running", "done", "failed"]
RunStatus = Literal["running", "done", "rejected", "failed"]

# 実行順（= stage_seq 1..6 の割当順）。モジュール docstring 参照。
STAGE_ORDER: tuple[StageName, ...] = ("collect", "subscore", "synthesis", "llm_overlay", "bracket", "verify")


class StageEvent(BaseModel):
    """1 ステージの1状態遷移（`inference_traces` の1行に対応する入力）."""

    model_config = ConfigDict(frozen=True)

    stage: StageName
    stage_status: StageStatus
    payload: dict[str, object]


class InferenceRunSummary(BaseModel):
    """`GET /api/inference/runs` の1件（run_id ごとの最新状態）."""

    model_config = ConfigDict(frozen=True)

    run_id: str
    symbol: str
    horizon_type: str
    status: RunStatus
    started_at: str
    finished_at: str | None
    pick_id: str | None


class InferenceOutcome(BaseModel):
    """`orchestrator.run_inference` の戻り値 — 台帳化するピック or 却下情報のどちらか一方."""

    model_config = ConfigDict(frozen=True)

    run_id: str
    symbol: str
    status: RunStatus
    pick: LedgerEntry | None = None
    rejected: RejectedPick | None = None
    # 🆕 P12: status="done" のときのみ設定される。Gemini shadow 判定を `pick_id` の
    # DB 確定後（`pipeline.run_picks` の `pl.insert_picks` 完了後）に呼ぶために必要な、
    # `run_inference` 内部でのみ計算済みの値（二重計算しない）。
    llm_prompt: str | None = None
    current_price: float | None = None
    atr: float | None = None
