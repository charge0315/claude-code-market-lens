"""AI 推論オーケストレータ — stage DAG（🆕 N4、`plans/03_システム設計` §3.1）.

collect → subscore → synthesis → llm_overlay → bracket → verify の6ステージを、ステージ単位で
`inference_traces` へ逐次記録する。各ステージは既存の移植済みサービス（recommender /
llm.registry で解決した LLM プロバイダ / bracket / E1〜E3 ゲート / calibration）を呼ぶだけの
薄いラッパで、新しいスコアリング・判定ロジックは持たない —
`services/picks/pipeline.py` の旧・ショートリストループの本体をそのまま移設したもの。

🔧 §3.1 の名目上の並び（collect→subscore→llm_overlay→synthesis→...）とは異なり、synthesis は
llm_overlay より **前** に実行する（LLM プロンプトが recommender の合成結果を埋め込むため。
実装順序の根拠は `backend/models/inference.py` の docstring 参照）。また confidence_raw は
doc 上は bracket ステージの算出物とされるが、実際は llm_overlay（LLM の構造化出力）から
そのまま得られる値であり、bracket ステージはそれに E2/対立シグナルキャップを適用してから
`finalize_bracket` を呼ぶ役割を担う。E1〜E3 のハード除外・確度較正・確度フロアは doc 通り
verify ステージへ集約した。
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import datetime
from typing import cast

from backend.models.inference import InferenceOutcome
from backend.models.pick import Direction, HorizonType, LedgerEntry, RejectedPick, SubScores
from backend.services.db.inference_trace_db import attach_pick_id, insert_trace_event
from backend.services.db.pick_outcome_db import cohort_winrate
from backend.services.db.shadow_prediction_db import insert_shadow_prediction
from backend.services.jst_time import JST
from backend.services.ledger import prediction_ledger as pl
from backend.services.llm.errors import LLMError
from backend.services.llm.provider import LLMProvider
from backend.services.llm.registry import resolve_feature_provider, resolve_shadow_providers
from backend.services.picks.bracket import finalize_bracket, standardize_holding_period
from backend.services.picks.prompt import build_pick_prompt
from backend.services.registry.calibration import apply_calibration
from backend.services.vault.brand_notes_service import get_brand_note
from backend.services.vault.daily_note_service import read_daily_frontmatter
from backend.services.vault.knowledge_search_client import extract_related_daily_dates, search_ticker_notes

logger = logging.getLogger(__name__)

_VALUE_TRAP_CONFIDENCE_CAP = 35.0
_CONFLICTING_CONFIDENCE_CAP = 60.0
_MIN_CONFIDENCE = 40.0
# E3 実測勝率ゲート: コホート約定 n がこれ以上で、勝率がこれ未満なら除外。
_WINRATE_GATE = 0.45
_WINRATE_GATE_MIN_SAMPLE = 20

_DIRECTION_MAP: dict[str, str] = {"bullish": "bullish", "bearish": "bearish", "neutral": "neutral", "mixed": "neutral"}


def _as_dict(value: object) -> dict[str, object]:
    """`rec` / `raw` の入れ子フィールドを安全に dict へ絞り込む（非 dict は空）."""
    return value if isinstance(value, dict) else {}


def _num(value: object) -> float | None:
    """数値なら float、それ以外（bool 含む）は None."""
    if isinstance(value, bool):
        return None
    return float(value) if isinstance(value, (int, float)) else None


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


class _Recorder:
    """1 run 分のステージイベントを `inference_traces` へ逐次 INSERT する薄いヘルパ."""

    def __init__(self, run_id: str, symbol: str, horizon_type: str) -> None:
        self.run_id = run_id
        self.symbol = symbol
        self.horizon_type = horizon_type
        self.started_at = datetime.now(JST).isoformat(timespec="seconds")
        self._seq = 0

    async def emit(
        self, stage: str, stage_status: str, payload: dict[str, object], *, run_status: str, pick_id: str | None = None
    ) -> None:
        self._seq += 1
        finished_at = datetime.now(JST).isoformat(timespec="seconds") if run_status != "running" else None
        await insert_trace_event(
            run_id=self.run_id,
            symbol=self.symbol,
            horizon_type=self.horizon_type,
            status=run_status,
            stage=stage,
            stage_status=stage_status,
            stage_seq=self._seq,
            payload=payload,
            started_at=self.started_at,
            finished_at=finished_at,
            pick_id=pick_id,
        )


async def _record_one_shadow_judgment(provider: LLMProvider, outcome: InferenceOutcome) -> None:
    """1 プロバイダぶんの shadow 判定を実行し `shadow_predictions` へ記録する（フェイルソフト）."""
    pick = outcome.pick
    if pick is None or outcome.llm_prompt is None or outcome.current_price is None:
        return
    try:
        raw = await provider.propose_stock_pick(ticker=pick.symbol, prompt=outcome.llm_prompt)
    except LLMError as e:
        logger.warning("%s shadow 判定に失敗しました（%s）: %s", provider.provider_id, pick.symbol, e)
        return

    if not raw.get("should_include", True):
        return

    raw_entry = _num(raw.get("buy_price"))
    raw_stop = _num(raw.get("stop_loss_price"))
    raw_target = _num(raw.get("take_profit_price"))
    confidence_raw = _num(raw.get("confidence"))
    if raw_entry is None or raw_stop is None or raw_target is None or confidence_raw is None:
        logger.warning("%s shadow 判定のレスポンス形式が不正です（%s）", provider.provider_id, pick.symbol)
        return

    bracket, reason = finalize_bracket(outcome.current_price, outcome.atr, raw_entry, raw_stop, raw_target)
    if bracket is None:
        logger.warning(
            "%s shadow 判定のブラケット検証に失敗しました（%s）: %s", provider.provider_id, pick.symbol, reason
        )
        return

    try:
        await insert_shadow_prediction(
            pick_id=pick.pick_id,
            run_id=outcome.run_id,
            challenger_version=f"{provider.provider_id}:{provider.model_id}",
            symbol=pick.symbol,
            horizon_type=pick.horizon_type,
            direction=pick.direction,
            entry=round(bracket.entry, 2),
            stop=round(bracket.stop, 2),
            target=round(bracket.target, 2),
            confidence_raw=confidence_raw,
            confidence=confidence_raw,
            payload={
                "reasoning": raw.get("reasoning"),
                "risk_factors": raw.get("risk_factors") or [],
                "holding_period_days": standardize_holding_period(raw.get("holding_period_days")),
            },
        )
    except Exception:  # noqa: BLE001 — 表示専用の challenger 記録。失敗しても本体は継続する
        logger.warning("%s shadow 判定の記録に失敗しました（%s）", provider.provider_id, pick.symbol, exc_info=True)


async def record_shadow_judgments(outcome: InferenceOutcome) -> None:
    """設定された shadow プロバイダ群（0〜複数、`LLM_SHADOW_PROVIDERS_STOCK_PICK`）に、
    公式パイプラインと同一のプロンプトを判定させ、`shadow_predictions` へ比較用に記録する.

    `shadow_predictions.pick_id` は `prediction_ledger.pick_id` への FK（外部キー制約 ON）の
    ため、呼び出しは **`pl.insert_picks` で台帳へ確定した後**（`pipeline.run_picks`）に限る
    — `run_inference` 実行時点ではまだ `pick_id` が DB に存在しない。

    表示専用の challenger 判定であり、失敗しても本体のピック生成には一切影響しない
    （フェイルソフト）。`direction` はこのアーキテクチャでは常に quant 由来（`pick.direction`）
    のため、challenger の応答からは再導出しない。3 値は公式パイプラインと同じ
    `finalize_bracket` を必ず通し、サーバ側検証をバイパスさせない（CLAUDE.md 3 値必須検証）。
    複数プロバイダが設定されていれば並行して判定させる。
    """
    providers = resolve_shadow_providers("stock_pick")
    if not providers:
        return
    await asyncio.gather(*(_record_one_shadow_judgment(p, outcome) for p in providers))


async def run_inference(
    *,
    symbol: str,
    horizon_type: str,
    batch_run_id: str,
    issued_at: str,
    model_version: str,
    rec: dict[str, object],
    atr: float | None,
    trend_score: float | None,
    news_block: str | None,
    trend_block: str | None,
    gate_horizon: int,
) -> InferenceOutcome:
    """1 銘柄ぶんの推論を stage DAG として実行し、トレースを記録しながらピック or 却下を返す.

    `rec`/`atr`/`trend_score` は呼び出し側（`pipeline.run_picks`）がショートリスト選定のために
    既に算出済みの値（collect/subscore/synthesis 相当）をそのまま受け取る — 二重計算しない。
    """
    run_id = str(uuid.uuid4())
    recorder = _Recorder(run_id, symbol, horizon_type)

    # --- stage 1: collect ---
    tech = _as_dict(rec.get("technical_signals"))
    current_price = _num(tech.get("current_price"))
    if current_price is None or current_price <= 0:
        rejected = RejectedPick(symbol=symbol, status="rejected_inconsistent", reason="現在値が取得できません")
        await recorder.emit("collect", "failed", {"current_price": current_price}, run_status="rejected")
        return InferenceOutcome(run_id=run_id, symbol=symbol, status="rejected", rejected=rejected)
    await recorder.emit("collect", "done", {"current_price": current_price, "atr_14": atr}, run_status="running")

    # --- stage 2: subscore ---
    await recorder.emit(
        "subscore",
        "done",
        {"score_breakdown": rec.get("score_breakdown"), "trend_score": trend_score},
        run_status="running",
    )

    # --- stage 3: synthesis ---
    await recorder.emit(
        "synthesis",
        "done",
        {
            "composite_score": rec.get("composite_score"),
            "concordance": rec.get("concordance"),
            "direction": rec.get("direction"),
            "source_contributions": rec.get("source_contributions"),
        },
        run_status="running",
    )

    # --- stage 4: llm_overlay ---
    brand = await get_brand_note(symbol)
    # ナレッジベース・ベクトル検索（🆕）で、当該銘柄コードにスコープした関連ノートを発見する
    # （`settings.kb_search_url` 未設定・検索失敗時は空リスト、フェイルソフト）。本文は
    # `knowledge_search_client` の境界で既に破棄済みで、Daily ノートの日付だけを受け取り、
    # 既存の frontmatter 専用関数で改めて読み直す（プロンプトインジェクション防御を維持）。
    kb_hits = await search_ticker_notes(str(brand.name) if brand and brand.name else symbol, code=symbol)
    related_daily = [fm for d in extract_related_daily_dates(kb_hits) if (fm := read_daily_frontmatter(d)) is not None]
    prompt = build_pick_prompt(
        horizon_type=horizon_type,
        recommendation=rec,
        current_price=current_price,
        atr=atr,
        brand_frontmatter=brand.to_prompt_dict() if brand else None,
        news_digest_block=news_block,
        trend_context_block=trend_block,
        related_daily_frontmatter=related_daily or None,
    )
    try:
        raw = await resolve_feature_provider("stock_pick").propose_stock_pick(ticker=symbol, prompt=prompt)
    except LLMError as e:
        rejected = RejectedPick(symbol=symbol, status="llm_error", reason=str(e))
        await recorder.emit("llm_overlay", "failed", {"error": str(e)}, run_status="rejected")
        return InferenceOutcome(run_id=run_id, symbol=symbol, status="rejected", rejected=rejected)

    if not raw.get("should_include", True):
        await recorder.emit(
            "llm_overlay", "done", {"should_include": False, "reasoning": raw.get("reasoning")}, run_status="rejected"
        )
        rejected = RejectedPick(symbol=symbol, status="rejected_hard_excluded", reason="AI が対象外と判断しました")
        return InferenceOutcome(run_id=run_id, symbol=symbol, status="rejected", rejected=rejected)

    raw_entry = _num(raw.get("buy_price"))
    raw_stop = _num(raw.get("stop_loss_price"))
    raw_target = _num(raw.get("take_profit_price"))
    confidence_raw = _num(raw.get("confidence"))
    if raw_entry is None or raw_stop is None or raw_target is None or confidence_raw is None:
        await recorder.emit("llm_overlay", "failed", {"raw": raw}, run_status="rejected")
        reason = "AI レスポンスの数値形式が不正です"
        rejected = RejectedPick(symbol=symbol, status="rejected_inconsistent", reason=reason)
        return InferenceOutcome(run_id=run_id, symbol=symbol, status="rejected", rejected=rejected)

    await recorder.emit(
        "llm_overlay",
        "done",
        {
            "should_include": True,
            "confidence_raw": confidence_raw,
            "buy_price": raw_entry,
            "stop_loss_price": raw_stop,
            "take_profit_price": raw_target,
            "risk_factors": raw.get("risk_factors") or [],
        },
        run_status="running",
    )

    # --- stage 5: bracket ---
    capped = confidence_raw
    if _as_dict(rec.get("fundamental_signals")).get("value_trap"):
        capped = min(capped, _VALUE_TRAP_CONFIDENCE_CAP)  # E2
    if tech.get("signal_agreement") == "conflicting":
        capped = min(capped, _CONFLICTING_CONFIDENCE_CAP)

    bracket, bracket_reason = finalize_bracket(current_price, atr, raw_entry, raw_stop, raw_target)
    if bracket is None:
        await recorder.emit(
            "bracket", "failed", {"reason": bracket_reason, "capped_confidence": capped}, run_status="rejected"
        )
        rejected = RejectedPick(symbol=symbol, status="rejected_inconsistent", reason=bracket_reason or "3 値不整合")
        return InferenceOutcome(run_id=run_id, symbol=symbol, status="rejected", rejected=rejected)

    await recorder.emit(
        "bracket",
        "done",
        {"entry": bracket.entry, "stop": bracket.stop, "target": bracket.target, "capped_confidence": capped},
        run_status="running",
    )

    # --- stage 6: verify ---
    if rec.get("recommendation") == "SELL":  # E1
        await recorder.emit("verify", "failed", {"reason": "recommender SELL"}, run_status="rejected")
        rejected = RejectedPick(
            symbol=symbol, status="rejected_hard_excluded", reason="recommender の判定が SELL のため除外"
        )
        return InferenceOutcome(run_id=run_id, symbol=symbol, status="rejected", rejected=rejected)

    # 確度の事後較正（CL-7 / N3）。台帳が薄いうちは較正器が無く恒等写像のまま。
    confidence, _calib_method = apply_calibration(horizon_type, gate_horizon, capped)

    raw_direction = str(rec.get("direction") or "neutral")
    direction = cast("Direction", _DIRECTION_MAP.get(raw_direction, "neutral"))
    bucket = pl.confidence_bucket(confidence)

    # E3: 実測勝率ゲート。決着済みコホート（確度バケット × 方向）の勝率が閾値未満で、
    # かつ約定サンプルが十分（>= _WINRATE_GATE_MIN_SAMPLE）なら、LLM の確度に関わらず除外する。
    win_rate, n_filled = await cohort_winrate(confidence_bucket=bucket, direction=direction, horizon_days=gate_horizon)
    if n_filled >= _WINRATE_GATE_MIN_SAMPLE and win_rate is not None and win_rate < _WINRATE_GATE:
        reason = (
            f"実測勝率ゲート: {bucket}/{direction} コホート勝率 {win_rate:.0%}"
            f"（n={n_filled}）が基準 {_WINRATE_GATE:.0%} 未満"
        )
        await recorder.emit(
            "verify", "failed", {"reason": reason, "win_rate": win_rate, "n_filled": n_filled}, run_status="rejected"
        )
        rejected = RejectedPick(symbol=symbol, status="rejected_hard_excluded", reason=reason)
        return InferenceOutcome(run_id=run_id, symbol=symbol, status="rejected", rejected=rejected)

    if confidence < _MIN_CONFIDENCE:
        reason = f"確度 {confidence:.0f}% が基準（{_MIN_CONFIDENCE:.0f}%）未満"
        await recorder.emit("verify", "failed", {"reason": reason, "confidence": confidence}, run_status="rejected")
        rejected = RejectedPick(symbol=symbol, status="rejected_low_confidence", reason=reason)
        return InferenceOutcome(run_id=run_id, symbol=symbol, status="rejected", rejected=rejected)

    pick = LedgerEntry(
        pick_id=pl.new_pick_id(),
        run_id=batch_run_id,
        issued_at=issued_at,
        horizon_type=cast("HorizonType", horizon_type),
        symbol=symbol,
        direction=direction,
        entry=round(bracket.entry, 2),
        stop=round(bracket.stop, 2),
        target=round(bracket.target, 2),
        sub_scores=_sub_scores(rec, trend_score),
        composite_score=_num(rec.get("composite_score")) or 50.0,
        concordance=_num(rec.get("concordance")) or 0.0,
        confidence_raw=confidence_raw,
        confidence=confidence,
        confidence_bucket=bucket,
        feature_snapshot=_feature_snapshot(rec, atr, trend_score),
        rationale_struct={
            "recommender_reasoning": rec.get("reasoning"),
            "llm_risk_factors": raw.get("risk_factors") or [],
            "holding_period_days": standardize_holding_period(raw.get("holding_period_days")),
        },
        rationale_text=str(raw.get("reasoning") or "総合スコアに基づく判定"),
        model_version=model_version,
        source_contributions=_as_dict(rec.get("source_contributions")),
        created_at=datetime.now(JST).isoformat(timespec="seconds"),
    )
    await recorder.emit(
        "verify",
        "done",
        {"confidence": confidence, "confidence_bucket": bucket, "win_rate": win_rate, "n_filled": n_filled},
        run_status="done",
        pick_id=pick.pick_id,
    )
    # 確定したピック ID を、この run の全ステージ行へ遡って紐付ける（銘柄詳細画面が
    # pick_id からトレース全体を引けるようにするため。collect〜bracket は当初 None）。
    await attach_pick_id(run_id, pick.pick_id)

    # 🆕 P12: `prompt`/`current_price`/`atr` を outcome に載せて返す。Gemini shadow 判定
    # （`record_gemini_shadow_judgment`）は `pick_id` が `prediction_ledger` へ確定した後
    # （`pipeline.run_picks` の `pl.insert_picks` 完了後）に呼ぶ必要があるため、ここでは
    # 呼ばずに必要な値だけを引き渡す（FK 制約により早すぎる呼び出しは記録が失敗する）。
    return InferenceOutcome(
        run_id=run_id,
        symbol=symbol,
        status="done",
        pick=pick,
        llm_prompt=prompt,
        current_price=current_price,
        atr=atr,
    )
