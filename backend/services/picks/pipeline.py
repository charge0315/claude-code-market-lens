"""中長期 / 短期 ピック生成パイプライン.

Market Lens `stock_pick_service.py` の「定量スクリーニング → LLM 深掘り」の二段構成を、
Alpha Forge 用に再設計して移植（🔧）。896 行の同ファイルは Market Lens 固有の当日ロック
（`stock_pick_runs` JSON blob）・`panel_context`・`signal_scan_report` 統合を含むため、
Alpha Forge は自前の `prediction_ledger` を中心に据えた薄いパイプラインにする。

流れ（`plans/01_PRD` §5.3、`plans/03` §3.1）:
1. 候補プール（`ranking_service` の値上がり/値下がり/出来高上位）を作る。
2. `recommender.compute_recommendation`（Vault frontmatter フォールバック付き）でスコアリングし、
   合成スコア降順にショートリスト化する。
3. 各候補を LLM（`anthropic_client.propose_stock_pick`、forced tool-use）へ深掘りし、
   3 値ブラケットを取得 → `bracket.finalize_bracket` でサーバ側検証 + ATR クランプ。
4. ハード除外: E1 recommender SELL / E2 value_trap 確度キャップ / (E3 実測勝率ゲートは P4 以降)。
   確度フロア未満は却下。
5. 生き残りを `prediction_ledger` へ台帳化（`feature_snapshot` 完全版 + `source_contributions`）。

LLM プロンプトへ注入するのは frontmatter / 構造化フィールドのみ（`services/picks/prompt.py`）。
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Mapping
from datetime import datetime
from typing import cast

from backend.services.anthropic_client import anthropic_client
from backend.services.anthropic_errors import AnthropicError
from backend.services.data.data_fetcher import get_stock_data
from backend.services.data.ranking_service import get_rankings
from backend.services.data.trend.context import render_trend_context
from backend.services.db.pick_outcome_db import cohort_winrate
from backend.services.jst_time import JST
from backend.services.learning.panel_feature_service import get_cached_panel_context
from backend.services.ledger import prediction_ledger as pl
from backend.services.picks.bracket import finalize_bracket, standardize_holding_period
from backend.services.picks.prompt import build_pick_prompt
from backend.services.registry.calibration import apply_calibration
from backend.services.registry.model_registry import bootstrap_champion_if_missing, ensure_registered
from backend.services.scoring.fundamental_analyzer import get_fundamental_with_vault_fallback
from backend.services.scoring.ml_score_provider import (
    MlScoreProvider,
    load_champion_pool_classifier,
    make_pool_ml_score_provider,
)
from backend.services.scoring.recommender import compute_recommendation, null_ml_score
from backend.services.scoring.signal_scan_scoring import compute_trend_score
from backend.services.scoring.technical_analysis import compute_atr
from backend.services.vault.brand_notes_service import get_brand_note
from backend.services.vault.news_digest_service import get_market_news_digest, render_news_digest_block

from backend.models.pick import (  # isort: skip
    Direction,
    HorizonType,
    LedgerEntry,
    PickRunResult,
    PickSummary,
    RejectedPick,
    SubScores,
)

logger = logging.getLogger(__name__)

MODEL_VERSION = "baseline-2026-09-11"

_ATR_PERIOD = 14
_ATR_LOOKBACK = "3mo"
_MIN_CONFIDENCE = 40.0
_VALUE_TRAP_CONFIDENCE_CAP = 35.0
_CONFLICTING_CONFIDENCE_CAP = 60.0
# E3 実測勝率ゲート: コホート約定 n がこれ以上で、勝率がこれ未満なら除外。
_WINRATE_GATE = 0.45
_WINRATE_GATE_MIN_SAMPLE = 20

# horizon 別の候補プール / ショートリスト設定。
_CONFIG: dict[str, dict[str, int]] = {
    "mid_term": {"pool_limit": 30, "shortlist": 12, "max_picks": 10},
    "short_term": {"pool_limit": 20, "shortlist": 8, "max_picks": 6},
}

_DIRECTION_MAP = {"bullish": "bullish", "bearish": "bearish", "neutral": "neutral", "mixed": "neutral"}


def _as_dict(value: object) -> dict[str, object]:
    """`rec` / `raw` の入れ子フィールドを安全に dict へ絞り込む（非 dict は空）."""
    return value if isinstance(value, dict) else {}


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


def _feature_snapshot(rec: dict[str, object], atr: float | None, trend_score: float | None) -> dict[str, object]:
    return {
        "score_breakdown": rec.get("score_breakdown"),
        "technical_signals": rec.get("technical_signals"),
        "fundamental_signals": rec.get("fundamental_signals"),
        "sentiment_average": rec.get("sentiment_average"),
        "ml_prediction_rate": rec.get("ml_prediction_rate"),
        "trend_score": trend_score,
        "atr_14": atr,
        "current_price": _as_dict(rec.get("technical_signals")).get("current_price"),
    }


def _sub_scores(rec: dict[str, object], trend_score: float | None) -> SubScores:
    breakdown = _as_dict(rec.get("score_breakdown"))
    return SubScores(
        technical=_num(breakdown.get("technical")) or 50.0,
        trend=float(trend_score) if trend_score is not None else 50.0,
        fundamental=_num(breakdown.get("fundamental")) or 50.0,
        sentiment=_num(breakdown.get("sentiment")) or 50.0,
    )


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

    # 断面プールモデル（N1 lane="ml_pool"）の ML ファクター。champion 未登録ならフォールバック
    # せず (None, None) を返す provider になる（recommender が残り3ファクターで再正規化）。
    panel_ctx = await get_cached_panel_context(issued_at[:10])
    pool_clf = await load_champion_pool_classifier()
    ml_score_provider = make_pool_ml_score_provider(panel_ctx, pool_clf)

    # スコアリング（合成スコア降順でショートリスト）。
    scored: list[tuple[str, dict[str, object], float | None, float | None]] = []
    for code in codes:
        fundamental = await get_fundamental_with_vault_fallback(code)
        rec, atr, trend_score = await asyncio.to_thread(_score_one, code, fundamental, ml_score_provider)
        scored.append((code, rec, atr, trend_score))
    scored.sort(key=lambda s: _num(s[1].get("composite_score")) or 0.0, reverse=True)
    shortlist = scored[: cfg["shortlist"]]

    picks: list[LedgerEntry] = []
    rejected: list[RejectedPick] = []

    for code, rec, atr, trend_score in shortlist:
        tech = _as_dict(rec.get("technical_signals"))
        current_price = _num(tech.get("current_price"))
        if current_price is None or current_price <= 0:
            rejected.append(RejectedPick(symbol=code, status="rejected_inconsistent", reason="現在値が取得できません"))
            continue

        brand = await get_brand_note(code)
        prompt = build_pick_prompt(
            horizon_type=horizon_type,
            recommendation=rec,
            current_price=current_price,
            atr=atr,
            brand_frontmatter=brand.to_prompt_dict() if brand else None,
            news_digest_block=news_block,
            trend_context_block=trend_block,
        )
        try:
            raw = await anthropic_client.propose_stock_pick(ticker=code, prompt=prompt)
        except AnthropicError as e:
            rejected.append(RejectedPick(symbol=code, status="llm_error", reason=str(e)))
            continue

        if not raw.get("should_include", True):
            rejected.append(
                RejectedPick(symbol=code, status="rejected_hard_excluded", reason="AI が対象外と判断しました")
            )
            continue

        raw_entry = _num(raw.get("buy_price"))
        raw_stop = _num(raw.get("stop_loss_price"))
        raw_target = _num(raw.get("take_profit_price"))
        confidence_raw = _num(raw.get("confidence"))
        if raw_entry is None or raw_stop is None or raw_target is None or confidence_raw is None:
            rejected.append(
                RejectedPick(symbol=code, status="rejected_inconsistent", reason="AI レスポンスの数値形式が不正です")
            )
            continue

        capped = confidence_raw
        if _as_dict(rec.get("fundamental_signals")).get("value_trap"):
            capped = min(capped, _VALUE_TRAP_CONFIDENCE_CAP)  # E2
        if tech.get("signal_agreement") == "conflicting":
            capped = min(capped, _CONFLICTING_CONFIDENCE_CAP)

        # 確度の事後較正（CL-7 / N3）。台帳が薄いうちは較正器が無く恒等写像のまま。
        gate_horizon = 3 if horizon_type == "short_term" else 20
        confidence, _calib_method = apply_calibration(horizon_type, gate_horizon, capped)

        bracket, reason = finalize_bracket(current_price, atr, raw_entry, raw_stop, raw_target)
        if bracket is None:
            rejected.append(RejectedPick(symbol=code, status="rejected_inconsistent", reason=reason or "3 値不整合"))
            continue

        if rec.get("recommendation") == "SELL":  # E1
            rejected.append(
                RejectedPick(
                    symbol=code, status="rejected_hard_excluded", reason="recommender の判定が SELL のため除外"
                )
            )
            continue

        raw_direction = str(rec.get("direction") or "neutral")
        direction = cast("Direction", _DIRECTION_MAP.get(raw_direction, "neutral"))
        bucket = pl.confidence_bucket(confidence)

        # E3: 実測勝率ゲート。決着済みコホート（確度バケット × 方向）の勝率が閾値未満で、
        # かつ約定サンプルが十分（>= _WINRATE_GATE_MIN_SAMPLE）なら、LLM の確度に関わらず除外する。
        # pick_outcomes が薄いうち（サンプル不足）はゲートが発動せず挙動は変わらない。
        win_rate, n_filled = await cohort_winrate(
            confidence_bucket=bucket, direction=direction, horizon_days=gate_horizon
        )
        if n_filled >= _WINRATE_GATE_MIN_SAMPLE and win_rate is not None and win_rate < _WINRATE_GATE:
            rejected.append(
                RejectedPick(
                    symbol=code,
                    status="rejected_hard_excluded",
                    reason=f"実測勝率ゲート: {bucket}/{direction} コホート勝率 {win_rate:.0%}"
                    f"（n={n_filled}）が基準 {_WINRATE_GATE:.0%} 未満",
                )
            )
            continue

        if confidence < _MIN_CONFIDENCE:
            rejected.append(
                RejectedPick(
                    symbol=code,
                    status="rejected_low_confidence",
                    reason=f"確度 {confidence:.0f}% が基準（{_MIN_CONFIDENCE:.0f}%）未満",
                )
            )
            continue

        picks.append(
            LedgerEntry(
                pick_id=pl.new_pick_id(),
                run_id=run_id,
                issued_at=issued_at,
                horizon_type=horizon,
                symbol=code,
                direction=direction,
                entry=round(bracket.entry, 2),
                stop=round(bracket.stop, 2),
                target=round(bracket.target, 2),
                sub_scores=_sub_scores(rec, trend_score),
                composite_score=_num(rec.get("composite_score")) or 50.0,
                concordance=_num(rec.get("concordance")) or 0.0,
                confidence_raw=confidence_raw,
                confidence=confidence,
                confidence_bucket=pl.confidence_bucket(confidence),
                feature_snapshot=_feature_snapshot(rec, atr, trend_score),
                rationale_struct={
                    "recommender_reasoning": rec.get("reasoning"),
                    "llm_risk_factors": raw.get("risk_factors") or [],
                    "holding_period_days": standardize_holding_period(raw.get("holding_period_days")),
                },
                rationale_text=str(raw.get("reasoning") or "総合スコアに基づく判定"),
                model_version=MODEL_VERSION,
                source_contributions=_as_dict(rec.get("source_contributions")),
                created_at=datetime.now(JST).isoformat(timespec="seconds"),
            )
        )
        if len(picks) >= cfg["max_picks"]:
            break

    if picks:
        await pl.insert_picks(picks)

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
