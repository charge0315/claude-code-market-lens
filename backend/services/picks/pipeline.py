"""中長期 / 短期 ピック生成パイプライン.

Market Lens `stock_pick_service.py` の「定量スクリーニング → LLM 深掘り」の二段構成を、
Alpha Forge 用に再設計して移植（🔧）。896 行の同ファイルは Market Lens 固有の当日ロック
（`stock_pick_runs` JSON blob）・`panel_context`・`signal_scan_report` 統合を含むため、
Alpha Forge は自前の `prediction_ledger` を中心に据えた薄いパイプラインにする。

流れ（`plans/01_PRD` §5.3、`plans/03` §3.1）:
1. 候補プール（`ranking_service` の値上がり/値下がり/出来高上位）を作る。
2. `recommender.compute_recommendation`（Vault frontmatter フォールバック付き）でスコアリングし、
   合成スコア降順にショートリスト化する。
3. ショートリスト各候補を `services/inference/orchestrator.run_inference`（P6, stage DAG）へ渡し、
   LLM 深掘り → 3 値ブラケット確定 → E1〜E3 ハード除外・確度較正・確度フロアを実行する
   （旧: 本ファイルにインライン実装していたショートリストループを P6 で orchestrator へ移設）。
4. 生き残りを `prediction_ledger` へ台帳化（`feature_snapshot` 完全版 + `source_contributions`）。

LLM プロンプトへ注入するのは frontmatter / 構造化フィールドのみ（`services/picks/prompt.py`）。
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Mapping
from datetime import datetime
from typing import cast

from backend.models.inference import InferenceOutcome
from backend.services.anthropic_client import anthropic_client
from backend.services.data.data_fetcher import get_stock_data
from backend.services.data.ranking_service import get_rankings
from backend.services.data.trend.context import render_trend_context
from backend.services.inference.orchestrator import record_gemini_shadow_judgment, run_inference
from backend.services.jst_time import JST
from backend.services.learning.panel_feature_service import get_cached_panel_context
from backend.services.ledger import prediction_ledger as pl
from backend.services.registry.model_registry import bootstrap_champion_if_missing, ensure_registered
from backend.services.scoring.fundamental_analyzer import get_fundamental_with_vault_fallback
from backend.services.scoring.ml_score_provider import (
    MlScoreProvider,
    combine_ml_score_providers,
    fetch_per_ticker_champion_rows,
    load_champion_pool_classifier,
    make_per_ticker_ensemble_provider,
    make_pool_ml_score_provider,
)
from backend.services.scoring.recommender import compute_recommendation, null_ml_score
from backend.services.scoring.signal_scan_scoring import compute_trend_score
from backend.services.scoring.technical_analysis import compute_atr
from backend.services.vault.news_digest_service import get_market_news_digest, render_news_digest_block

from backend.models.pick import (  # isort: skip
    HorizonType,
    LedgerEntry,
    PickRunResult,
    PickSummary,
    RejectedPick,
)

logger = logging.getLogger(__name__)

MODEL_VERSION = "baseline-2026-09-11"

_ATR_PERIOD = 14
_ATR_LOOKBACK = "3mo"

# horizon 別の候補プール / ショートリスト設定。
_CONFIG: dict[str, dict[str, int]] = {
    "mid_term": {"pool_limit": 30, "shortlist": 12, "max_picks": 10},
    "short_term": {"pool_limit": 20, "shortlist": 8, "max_picks": 6},
}


def _num(value: object) -> float | None:
    """数値なら float、それ以外（bool 含む）は None."""
    if isinstance(value, bool):
        return None
    return float(value) if isinstance(value, (int, float)) else None


async def _candidate_pool(horizon_type: str, limit: int) -> list[str]:
    """候補プール（4 桁コード列、順序保持・重複除去）を返す.

    `ranking_service` の値上がり / 出来高上位を母集団にする（短期は出来高寄り）。
    取得失敗時は空リスト（呼び出し元が empty で返す）。
    """
    try:
        rankings = await get_rankings(limit=limit)
    except Exception as e:  # noqa: BLE001 — 候補プール取得失敗（J-Quants 障害等）は empty 応答へ畳む
        logger.warning("候補プール取得に失敗: %s", e)
        return []

    if horizon_type == "short_term":
        ordered = [*rankings.volume_leaders, *rankings.gainers]
    else:
        ordered = [*rankings.gainers, *rankings.volume_leaders, *rankings.losers]

    seen: set[str] = set()
    out: list[str] = []
    for entry in ordered:
        if entry.code not in seen:
            seen.add(entry.code)
            out.append(entry.code)
        if len(out) >= limit:
            break
    return out


def _score_one(
    code: str, fundamental: Mapping[str, object], ml_score_provider: MlScoreProvider = null_ml_score
) -> tuple[dict[str, object], float | None, float | None]:
    """recommender スコアリング + ATR + trend サブスコアを同期で計算する（to_thread から呼ぶ）."""
    rec = compute_recommendation(code, fundamental=fundamental, ml_score_provider=ml_score_provider)
    df3 = get_stock_data(code, period=_ATR_LOOKBACK)
    atr = compute_atr(df3, _ATR_PERIOD)
    trend_score, _ = compute_trend_score(df3)
    return rec, atr, trend_score


async def run_picks(horizon_type: str) -> PickRunResult:
    """1 系統（中長期 or 短期）のピックを生成し、台帳化して結果を返す."""
    cfg = _CONFIG[horizon_type]
    run_id = pl.new_run_id()
    issued_at = datetime.now(JST).isoformat(timespec="seconds")

    horizon = cast("HorizonType", horizon_type)

    # モデルレジストリへ登録し、その lane に champion が無ければ無条件で champion にする
    # （N1、`plans/03` §1.4）。2 本目以降のバージョンは昇格ゲートを通さない限り champion にならない。
    await ensure_registered(MODEL_VERSION, lane=horizon_type)
    await bootstrap_champion_if_missing(horizon_type, MODEL_VERSION)

    if not anthropic_client.is_configured:
        return PickRunResult(
            run_id=run_id,
            horizon_type=horizon,
            issued_at=issued_at,
            status="not_configured",
            picks=[],
            rejected=[],
            message="ANTHROPIC_API_KEY が未設定のためピックを生成できません",
        )

    codes = await _candidate_pool(horizon_type, cfg["pool_limit"])
    if not codes:
        return PickRunResult(
            run_id=run_id,
            horizon_type=horizon,
            issued_at=issued_at,
            status="empty",
            picks=[],
            rejected=[],
            message="候補プールを取得できませんでした（J-Quants 未設定 / 混雑の可能性）",
        )

    news_block = render_news_digest_block(await get_market_news_digest())
    # 最新トレンドスナップショット（読み取りのみ。同期は beat が別途行う）。
    trend_block = await render_trend_context()

    # 断面プールモデル（N1 lane="ml_pool"）+ 銘柄別アンサンブル（P9）の ML ファクターを並列合成する。
    # どちらも champion 未登録・推論失敗なら (None, None) を返し、recommender が残り3ファクター
    # で再正規化する（フォールバック不要）。銘柄別アンサンブルの champion 行は同期関数
    # （`ensemble_predictor.predict_ensemble_sync`）から非同期 DB I/O を呼べないため、
    # 各銘柄をスコアリングするスレッドへ渡す前にここで事前取得する。
    panel_ctx = await get_cached_panel_context(issued_at[:10])
    pool_clf = await load_champion_pool_classifier()
    pool_provider = make_pool_ml_score_provider(panel_ctx, pool_clf)

    # スコアリング（合成スコア降順でショートリスト）。
    scored: list[tuple[str, dict[str, object], float | None, float | None]] = []
    for code in codes:
        try:
            fundamental = await get_fundamental_with_vault_fallback(code)
            ticker_rows = await fetch_per_ticker_champion_rows(code)
            ml_score_provider = combine_ml_score_providers(
                pool_provider, make_per_ticker_ensemble_provider(ticker_rows)
            )
            rec, atr, trend_score = await asyncio.to_thread(_score_one, code, fundamental, ml_score_provider)
        except Exception as e:  # noqa: BLE001 — 1銘柄の取得/スコアリング失敗（サーキットブレーカー
            # オープン・レート制限等）で候補プール全体を落とさない。他の箇所（
            # `_build_raw_universe_frame` 等）と同じ「1銘柄失敗で全体を止めない」方針。
            logger.warning("スコアリングに失敗（銘柄をスキップ）: %s — %s", code, e)
            continue
        scored.append((code, rec, atr, trend_score))
    scored.sort(key=lambda s: _num(s[1].get("composite_score")) or 0.0, reverse=True)
    shortlist = scored[: cfg["shortlist"]]

    picks: list[LedgerEntry] = []
    rejected: list[RejectedPick] = []
    accepted_outcomes: list[InferenceOutcome] = []
    gate_horizon = 3 if horizon_type == "short_term" else 20

    for code, rec, atr, trend_score in shortlist:
        outcome = await run_inference(
            symbol=code,
            horizon_type=horizon_type,
            batch_run_id=run_id,
            issued_at=issued_at,
            model_version=MODEL_VERSION,
            rec=rec,
            atr=atr,
            trend_score=trend_score,
            news_block=news_block,
            trend_block=trend_block,
            gate_horizon=gate_horizon,
        )
        if outcome.pick is not None:
            picks.append(outcome.pick)
            accepted_outcomes.append(outcome)
            if len(picks) >= cfg["max_picks"]:
                break
        elif outcome.rejected is not None:
            rejected.append(outcome.rejected)

    if picks:
        await pl.insert_picks(picks)
        # 🆕 P12: Gemini shadow 判定は `shadow_predictions.pick_id` が `prediction_ledger` への
        # FK のため、台帳確定（`insert_picks`）の後でのみ呼べる。未設定・失敗時は無視（フェイルソフト）。
        for accepted in accepted_outcomes:
            await record_gemini_shadow_judgment(accepted)

    summaries = [
        PickSummary(
            pick_id=p.pick_id,
            issued_at=p.issued_at,
            horizon_type=p.horizon_type,
            symbol=p.symbol,
            direction=p.direction,
            entry=p.entry,
            stop=p.stop,
            target=p.target,
            composite_score=p.composite_score,
            concordance=p.concordance,
            confidence=p.confidence,
            confidence_bucket=p.confidence_bucket,
            rationale_text=p.rationale_text,
            model_version=p.model_version,
            source_contributions=p.source_contributions,
        )
        for p in picks
    ]

    status = "ok" if summaries else "empty"
    message = None if summaries else "本日は確度基準を満たす銘柄がなく見送りとしました"
    return PickRunResult(
        run_id=run_id,
        horizon_type=horizon,
        issued_at=issued_at,
        status=status,
        picks=summaries,
        rejected=rejected,
        message=message,
    )
