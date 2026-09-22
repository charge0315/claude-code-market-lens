"""任意銘柄のオンデマンド AI 推論トレース（🆕 P36）.

`/chart` 画面で選んだ任意銘柄（本日の AI ピック対象外も含む）について、その場で
`services/inference/orchestrator.run_inference` を1回だけ実行し、4分析〜検証ゲートまでの
全ステージをライブでトレース記録する「試し打ち」実行。`services/picks/pipeline.run_picks`
と異なり `prediction_ledger`/`pick_pool_snapshots` への書き込みは一切行わない
（`pl.insert_picks` を呼ばない）ため、台帳を汚さない。

コスト・安全性: 公式 LLM 呼び出し1回 + ニュースセンチメント等の隔離 LLM 呼び出し +
シャドウプロバイダ分（設定されていれば）が発生する。呼び出し元（`routers/inference.py`）が
`api_cost.is_daily_limit_exceeded()` で事前ブロックする。
"""

from __future__ import annotations

from datetime import datetime

from backend.models.inference import InferenceOutcome
from backend.models.pick import HorizonType, RejectedPick
from backend.services.data.trend.context import render_trend_context
from backend.services.inference.orchestrator import record_shadow_judgments, run_inference
from backend.services.jst_time import JST
from backend.services.llm.registry import resolve_feature_provider
from backend.services.picks.pipeline import MODEL_VERSION, build_pool_provider, score_candidate
from backend.services.vault.news_digest_service import get_market_news_digest, render_news_digest_block

# `pipeline.run_picks` の決着ゲート判定と同じ対応（短期=3営業日、中長期=20営業日）。
_GATE_HORIZON: dict[str, int] = {"mid_term": 20, "short_term": 3}


async def run_sandbox_inference(symbol: str, horizon_type: HorizonType, *, run_id: str) -> InferenceOutcome:
    """1 銘柄ぶんの推論を台帳化せずに実行し、`inference_traces`（+設定されていれば
    `shadow_predictions`、`pick_id=None`）へライブ記録する.

    `routers/inference.py` の `POST /api/inference/sandbox` がバックグラウンドタスクとして
    起動する。エンドポイントは `run_id` を即座に返して終わっているため、失敗もこの関数の
    戻り値ではなくトレース（`inference_traces`）経由でフロントへ伝える設計 —
    例外を外へ伝播させず `InferenceOutcome(status="rejected", ...)` に畳む。
    """
    issued_at = datetime.now(JST).isoformat(timespec="seconds")
    stock_pick_provider = resolve_feature_provider("stock_pick")
    if not stock_pick_provider.is_configured:
        return InferenceOutcome(
            run_id=run_id,
            symbol=symbol,
            status="rejected",
            rejected=RejectedPick(
                symbol=symbol,
                status="llm_error",
                reason=f"{stock_pick_provider.provider_id} の API キーが未設定のため推論を実行できません",
            ),
        )

    pool_provider = await build_pool_provider(issued_at[:10])
    try:
        rec, atr, trend_score = await score_candidate(symbol, pool_provider)
    except Exception as e:  # noqa: BLE001 — スコアリング失敗（存在しない銘柄コード等）は却下として返す
        return InferenceOutcome(
            run_id=run_id,
            symbol=symbol,
            status="rejected",
            rejected=RejectedPick(
                symbol=symbol, status="rejected_inconsistent", reason=f"スコアリングに失敗しました: {e}"
            ),
        )

    news_block = render_news_digest_block(await get_market_news_digest())
    trend_block = await render_trend_context()

    outcome = await run_inference(
        symbol=symbol,
        horizon_type=horizon_type,
        batch_run_id=f"sandbox-{run_id}",
        issued_at=issued_at,
        model_version=MODEL_VERSION,
        rec=rec,
        atr=atr,
        trend_score=trend_score,
        news_block=news_block,
        trend_block=trend_block,
        gate_horizon=_GATE_HORIZON[horizon_type],
        run_id=run_id,
    )
    # `pl.insert_picks` は意図的に呼ばない — prediction_ledger を汚さない「試し打ち」実行のため。
    if outcome.status == "done":
        await record_shadow_judgments(outcome, pick_id=None)
    return outcome
