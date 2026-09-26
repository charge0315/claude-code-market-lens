"""LLM の構造化応答を検証し、台帳行（ピック）か却下へ確定させる共通処理.

`orchestrator.run_inference` の llm_overlay 後半〜bracket〜verify を切り出したもの。公式判定と
プロンプト挑戦者（`prompt_challenger.py`）が **同じ検証・同じゲート** を通るようにするため、
1 か所に置く（挑戦者だけ緩い基準で採点されると昇格評価が不公平になる）。
ステージ記録は `StageEmitter` 経由で、挑戦者はトレースを書かない（`None` を渡す）。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal, Protocol, cast

from backend.models.pick import Direction, HorizonType, LedgerEntry, RejectedPick, SubScores
from backend.services.db.pick_outcome_db import cohort_winrate
from backend.services.jst_time import JST
from backend.services.ledger import prediction_ledger as pl
from backend.services.picks.bracket import finalize_bracket, standardize_holding_period
from backend.services.registry.calibration import apply_calibration
from backend.services.scoring.llm_news_sentiment_service import LlmNewsSentimentResult
from backend.services.vault.brand_notes_service import BrandNote

_VALUE_TRAP_CONFIDENCE_CAP = 35.0
_CONFLICTING_CONFIDENCE_CAP = 60.0
# 強いネガティブ×高確信度×高影響度のニュースセンチメント（🆕）のみで発動する confidence cap。
# 単一の補助シグナルであり、構造的な問題を示す value_trap ほど強くは効かせない
# （`_VALUE_TRAP_CONFIDENCE_CAP` より緩く、`_CONFLICTING_CONFIDENCE_CAP` よりやや厳しい）。
# ポジティブ判定で confidence を引き上げる処理は意図的に追加しない（非対称設計、
# 較正されていない新バイアスを確度スコアへ導入しないため）。
_NEWS_SENTIMENT_CONFIDENCE_CAP = 55.0
_NEWS_SENTIMENT_CAP_MIN_LLM_CONFIDENCE = 50.0
_NEWS_SENTIMENT_CAP_MIN_IMPACT = 50.0
_MIN_CONFIDENCE = 40.0
# E3 実測勝率ゲート: コホート約定 n がこれ以上で、勝率がこれ未満なら除外。
_WINRATE_GATE = 0.45
_WINRATE_GATE_MIN_SAMPLE = 20

_DIRECTION_MAP: dict[str, str] = {"bullish": "bullish", "bearish": "bearish", "neutral": "neutral", "mixed": "neutral"}


def as_dict(value: object) -> dict[str, object]:
    """`rec` / `raw` の入れ子フィールドを安全に dict へ絞り込む（非 dict は空）."""
    return value if isinstance(value, dict) else {}


def num(value: object) -> float | None:
    """数値なら float、それ以外（bool 含む）は None."""
    if isinstance(value, bool):
        return None
    return float(value) if isinstance(value, (int, float)) else None


class StageEmitter(Protocol):
    """ステージイベントの記録先（`orchestrator._Recorder`）。挑戦者は記録しない."""

    async def emit(
        self, stage: str, stage_status: str, payload: dict[str, object], *, run_status: str, pick_id: str | None = None
    ) -> None: ...


@dataclass(frozen=True)
class JudgmentContext:
    """1 銘柄の判定に使う、LLM 呼び出し前に確定済みの材料（公式と挑戦者で共通）."""

    symbol: str
    horizon_type: str
    batch_run_id: str
    issued_at: str
    rec: dict[str, object]
    atr: float | None
    trend_score: float | None
    gate_horizon: int
    current_price: float
    brand: BrandNote | None
    news_sentiment: LlmNewsSentimentResult | None
    supply_demand: dict[str, object] | None
    earnings_surprise: dict[str, object] | None


@dataclass(frozen=True)
class Judgment:
    """判定結果。`pick` か `rejected` のどちらか一方だけが入る."""

    pick: LedgerEntry | None = None
    rejected: RejectedPick | None = None


def _pit_sentiment_snapshot(news_sentiment: LlmNewsSentimentResult | None) -> dict[str, object] | None:
    """LLM ニュースセンチメント判定の生フィールド（enum/number のみ）を `feature_snapshot` 用に返す.

    🆕 P29: `reasoning`（自由記述）は含めない — `llm_news_sentiment_service` の
    enum/number 転送境界を `feature_snapshot` の側でも一貫させる。
    """
    if news_sentiment is None:
        return None
    return {
        "llm_sentiment_label": news_sentiment.sentiment_label,
        "llm_sentiment_score": news_sentiment.sentiment_score,
        "llm_impact_score": news_sentiment.impact_score,
        "llm_confidence": news_sentiment.confidence,
        "news_count": news_sentiment.news_count,
    }


def _feature_snapshot(ctx: JudgmentContext) -> dict[str, object]:
    rec = ctx.rec
    return {
        "score_breakdown": rec.get("score_breakdown"),
        "technical_signals": rec.get("technical_signals"),
        "fundamental_signals": rec.get("fundamental_signals"),
        "sentiment_average": rec.get("sentiment_average"),
        "ml_prediction_rate": rec.get("ml_prediction_rate"),
        "trend_score": ctx.trend_score,
        "atr_14": ctx.atr,
        "current_price": as_dict(rec.get("technical_signals")).get("current_price"),
        # 🆕 P29: 遡及的な特徴量エンジニアリング・生粒度 PSI 監視のための生値（`plans/03` §1.9）。
        # Vault frontmatter の生の財務指標（数値・enum のみ）。
        "pit_fundamental": ctx.brand.to_prompt_dict() if ctx.brand else None,
        "pit_sentiment": _pit_sentiment_snapshot(ctx.news_sentiment),
        # 🆕 週末信用取引残高（中長期限定、`supply_demand_analyzer`）。短期ピックでは常に None。
        "pit_supply_demand": ctx.supply_demand,
        # 🆕 決算サプライズ・予想修正モメンタム（`earnings_surprise_analyzer`）。短期・中長期の両方が対象。
        "pit_earnings_surprise": ctx.earnings_surprise,
    }


def _sub_scores(rec: dict[str, object], trend_score: float | None) -> SubScores:
    breakdown = as_dict(rec.get("score_breakdown"))
    return SubScores(
        technical=num(breakdown.get("technical")) or 50.0,
        trend=float(trend_score) if trend_score is not None else 50.0,
        fundamental=num(breakdown.get("fundamental")) or 50.0,
        sentiment=num(breakdown.get("sentiment")) or 50.0,
    )


def _capped_confidence(ctx: JudgmentContext, confidence_raw: float) -> float:
    """E2（value trap）・対立シグナル・強いネガティブニュースの確度上限を適用する."""
    capped = confidence_raw
    if as_dict(ctx.rec.get("fundamental_signals")).get("value_trap"):
        capped = min(capped, _VALUE_TRAP_CONFIDENCE_CAP)  # E2
    if as_dict(ctx.rec.get("technical_signals")).get("signal_agreement") == "conflicting":
        capped = min(capped, _CONFLICTING_CONFIDENCE_CAP)
    ns = ctx.news_sentiment
    if (
        ns is not None
        and ns.sentiment_label in ("negative", "strongly_negative")
        and ns.confidence >= _NEWS_SENTIMENT_CAP_MIN_LLM_CONFIDENCE
        and ns.impact_score >= _NEWS_SENTIMENT_CAP_MIN_IMPACT
    ):
        capped = min(capped, _NEWS_SENTIMENT_CONFIDENCE_CAP)
    return capped


class _NullEmitter:
    """トレースを書かない emitter（プロンプト挑戦者用）."""

    async def emit(
        self, stage: str, stage_status: str, payload: dict[str, object], *, run_status: str, pick_id: str | None = None
    ) -> None:
        return None


async def judge(
    ctx: JudgmentContext,
    raw: dict[str, object],
    *,
    model_version: str,
    is_shadow: bool,
    emitter: StageEmitter | None,
) -> Judgment:
    """LLM の構造化応答 `raw` を検証し、E1〜E3・確度較正・確度フロアを通してピックか却下を返す."""
    rec = emitter or _NullEmitter()
    symbol = ctx.symbol

    def _reject(
        status: Literal["rejected_inconsistent", "rejected_hard_excluded", "rejected_low_confidence"], reason: str
    ) -> Judgment:
        return Judgment(rejected=RejectedPick(symbol=symbol, status=status, reason=reason))

    if not raw.get("should_include", True):
        await rec.emit(
            "llm_overlay", "done", {"should_include": False, "reasoning": raw.get("reasoning")}, run_status="rejected"
        )
        return _reject("rejected_hard_excluded", "AI が対象外と判断しました")

    raw_entry = num(raw.get("buy_price"))
    raw_stop = num(raw.get("stop_loss_price"))
    raw_target = num(raw.get("take_profit_price"))
    confidence_raw = num(raw.get("confidence"))
    if raw_entry is None or raw_stop is None or raw_target is None or confidence_raw is None:
        await rec.emit("llm_overlay", "failed", {"raw": raw}, run_status="rejected")
        return _reject("rejected_inconsistent", "AI レスポンスの数値形式が不正です")

    news_rationale = ctx.news_sentiment.to_rationale_dict() if ctx.news_sentiment else None
    await rec.emit(
        "llm_overlay",
        "done",
        {
            "should_include": True,
            "confidence_raw": confidence_raw,
            "buy_price": raw_entry,
            "stop_loss_price": raw_stop,
            "take_profit_price": raw_target,
            "risk_factors": raw.get("risk_factors") or [],
            "news_sentiment": news_rationale,
            "supply_demand": ctx.supply_demand,
            "earnings_surprise": ctx.earnings_surprise,
        },
        run_status="running",
    )

    # --- stage 5: bracket ---
    capped = _capped_confidence(ctx, confidence_raw)
    bracket, bracket_reason = finalize_bracket(ctx.current_price, ctx.atr, raw_entry, raw_stop, raw_target)
    if bracket is None:
        await rec.emit(
            "bracket", "failed", {"reason": bracket_reason, "capped_confidence": capped}, run_status="rejected"
        )
        return _reject("rejected_inconsistent", bracket_reason or "3 値不整合")
    await rec.emit(
        "bracket",
        "done",
        {"entry": bracket.entry, "stop": bracket.stop, "target": bracket.target, "capped_confidence": capped},
        run_status="running",
    )

    # --- stage 6: verify ---
    if ctx.rec.get("recommendation") == "SELL":  # E1
        await rec.emit("verify", "failed", {"reason": "recommender SELL"}, run_status="rejected")
        return _reject("rejected_hard_excluded", "recommender の判定が SELL のため除外")

    # 確度の事後較正（CL-7 / N3）。台帳が薄いうちは較正器が無く恒等写像のまま。
    confidence, _calib_method = apply_calibration(ctx.horizon_type, ctx.gate_horizon, capped)
    direction = cast("Direction", _DIRECTION_MAP.get(str(ctx.rec.get("direction") or "neutral"), "neutral"))
    bucket = pl.confidence_bucket(confidence)

    # E3: 実測勝率ゲート。決着済みコホート（確度バケット × 方向）の勝率が閾値未満で、
    # かつ約定サンプルが十分（>= _WINRATE_GATE_MIN_SAMPLE）なら、LLM の確度に関わらず除外する。
    win_rate, n_filled = await cohort_winrate(
        confidence_bucket=bucket, direction=direction, horizon_days=ctx.gate_horizon
    )
    if n_filled >= _WINRATE_GATE_MIN_SAMPLE and win_rate is not None and win_rate < _WINRATE_GATE:
        reason = (
            f"実測勝率ゲート: {bucket}/{direction} コホート勝率 {win_rate:.0%}"
            f"（n={n_filled}）が基準 {_WINRATE_GATE:.0%} 未満"
        )
        await rec.emit(
            "verify", "failed", {"reason": reason, "win_rate": win_rate, "n_filled": n_filled}, run_status="rejected"
        )
        return _reject("rejected_hard_excluded", reason)

    if confidence < _MIN_CONFIDENCE:
        reason = f"確度 {confidence:.0f}% が基準（{_MIN_CONFIDENCE:.0f}%）未満"
        await rec.emit("verify", "failed", {"reason": reason, "confidence": confidence}, run_status="rejected")
        return _reject("rejected_low_confidence", reason)

    pick = LedgerEntry(
        pick_id=pl.new_pick_id(),
        run_id=ctx.batch_run_id,
        issued_at=ctx.issued_at,
        horizon_type=cast("HorizonType", ctx.horizon_type),
        symbol=symbol,
        direction=direction,
        entry=round(bracket.entry, 2),
        stop=round(bracket.stop, 2),
        target=round(bracket.target, 2),
        sub_scores=_sub_scores(ctx.rec, ctx.trend_score),
        composite_score=num(ctx.rec.get("composite_score")) or 50.0,
        concordance=num(ctx.rec.get("concordance")) or 0.0,
        confidence_raw=confidence_raw,
        confidence=confidence,
        confidence_bucket=bucket,
        feature_snapshot=_feature_snapshot(ctx),
        rationale_struct={
            "recommender_reasoning": ctx.rec.get("reasoning"),
            "llm_risk_factors": raw.get("risk_factors") or [],
            "holding_period_days": standardize_holding_period(raw.get("holding_period_days")),
            "news_sentiment": news_rationale,
            "supply_demand": ctx.supply_demand,
            "earnings_surprise": ctx.earnings_surprise,
        },
        rationale_text=str(raw.get("reasoning") or "総合スコアに基づく判定"),
        model_version=model_version,
        source_contributions=as_dict(ctx.rec.get("source_contributions")),
        is_shadow=is_shadow,
        created_at=datetime.now(JST).isoformat(timespec="seconds"),
    )
    await rec.emit(
        "verify",
        "done",
        {"confidence": confidence, "confidence_bucket": bucket, "win_rate": win_rate, "n_filled": n_filled},
        run_status="done",
        pick_id=pick.pick_id,
    )
    return Judgment(pick=pick)
