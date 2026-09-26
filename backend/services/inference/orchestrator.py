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

🆕 ニュース見出しLLMセンチメント（`llm_news_sentiment_service`）は独立した隔離LLM呼び出しで、
新規ステージは追加せず llm_overlay の payload 拡張として記録する（既存6ステージの後方互換を
壊さないため）。強いネガティブ判定のみ bracket ステージで confidence cap を追加適用する。

🆕 週末信用取引残高（`supply_demand_analyzer`、中長期ピック限定・ユーザー指示）も同じ理由で
新規ステージを追加せず llm_overlay の payload 拡張として記録する。構造化数値のみで自由記述
本文が無いため、ニュースセンチメントと異なり隔離LLM呼び出しは不要。composite_score や
confidence cap には統合しない（v1、較正・promotion gate への影響を避けるため）。

🆕 決算サプライズ・予想修正モメンタム（`earnings_surprise_analyzer`）も同じ理由で新規ステージを
追加せず llm_overlay の payload 拡張として記録する。需給軸と異なりホライズンによる gate は
行わない（決算サプライズは発表直後の値動きに直結するイベントドリブン材料のため短期・中長期の
両方が対象、ニュースセンチメントと同じ扱い）。J-Quants の構造化数値のみで自由記述本文が無いため
隔離LLM呼び出しは不要。composite_score や confidence cap には統合しない（v1、需給軸と同じ理由）。

🆕 llm_overlay の応答検証〜bracket〜verify（E1〜E3・確度較正・確度フロア・台帳行の組み立て）は
`judgment.py` へ切り出した。プロンプト挑戦者（`prompt_challenger.py`）が公式と同じ基準で
採点されるようにするため（挑戦者だけ基準が違うと昇格評価が不公平になる）。
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import datetime

from backend.models.inference import InferenceOutcome
from backend.models.pick import RejectedPick
from backend.services.db.inference_trace_db import attach_pick_id, insert_trace_event
from backend.services.db.shadow_prediction_db import insert_shadow_prediction
from backend.services.inference.judgment import JudgmentContext, judge, num
from backend.services.inference.prompt_challenger import judge_with_challenger
from backend.services.jst_time import JST
from backend.services.learning.pit_snapshot_service import (
    record_earnings_surprise_snapshot,
    record_llm_sentiment_snapshot,
    record_supply_demand_snapshot,
)
from backend.services.llm.errors import LLMError
from backend.services.llm.provider import LLMProvider
from backend.services.llm.registry import resolve_feature_provider, resolve_shadow_providers
from backend.services.picks.bracket import finalize_bracket, standardize_holding_period
from backend.services.picks.prompt import build_pick_prompt
from backend.services.scoring.earnings_surprise_analyzer import (
    get_earnings_surprise_data,
    render_earnings_surprise_block,
)
from backend.services.scoring.llm_news_sentiment_service import (
    get_llm_news_sentiment,
    render_news_sentiment_block,
)
from backend.services.scoring.supply_demand_analyzer import get_supply_demand_data, render_supply_demand_block
from backend.services.vault.brand_notes_service import get_brand_note
from backend.services.vault.daily_note_service import read_daily_frontmatter
from backend.services.vault.knowledge_search_client import extract_related_daily_dates, search_ticker_notes

logger = logging.getLogger(__name__)


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


async def _record_one_shadow_judgment(provider: LLMProvider, outcome: InferenceOutcome, *, pick_id: str | None) -> None:
    """1 プロバイダぶんの shadow 判定を実行し `shadow_predictions` へ記録する（フェイルソフト）.

    `pick_id` は呼び出し元が明示的に渡す（`outcome.pick.pick_id` をそのまま使わない） —
    🆕 P36: `services/inference/sandbox.py`（任意銘柄のオンデマンド推論、`prediction_ledger`
    へ台帳化しない）から呼ぶ場合は `None` を渡す。`shadow_predictions.pick_id` は nullable な
    外部キー（`prediction_ledger.pick_id` 参照、`0001_baseline.py`）のため、台帳未確定の
    `pick.pick_id`（値はあるが `prediction_ledger` にまだ存在しない）をそのまま渡すと
    `PRAGMA foreign_keys=ON`（`services/db/database.py`）下で制約違反になる。
    """
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

    raw_entry = num(raw.get("buy_price"))
    raw_stop = num(raw.get("stop_loss_price"))
    raw_target = num(raw.get("take_profit_price"))
    confidence_raw = num(raw.get("confidence"))
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
            pick_id=pick_id,
            run_id=outcome.run_id,
            challenger_version=f"{provider.provider_id}:{provider.model_for('stock_pick')}",
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


async def record_shadow_judgments(outcome: InferenceOutcome, *, pick_id: str | None) -> None:
    """設定された shadow プロバイダ群（0〜複数、`LLM_SHADOW_PROVIDERS_STOCK_PICK`）に、
    公式パイプラインと同一のプロンプトを判定させ、`shadow_predictions` へ比較用に記録する.

    `pick_id` は呼び出し元が明示的に指定する（`shadow_predictions.pick_id` は
    `prediction_ledger.pick_id` への nullable な FK、外部キー制約 ON、`services/db/database.py`）。
    - `pipeline.run_picks` からの通常呼び出しは `outcome.pick.pick_id`（**`pl.insert_picks` で
      台帳へ確定した後**に限る — `run_inference` 実行時点ではまだ DB に存在しないため）。
    - 🆕 P36: `services/inference/sandbox.py`（任意銘柄のオンデマンド推論、台帳化しない）は
      `pick_id=None` を渡す（FK は nullable のため通る）。

    表示専用の challenger 判定であり、失敗しても本体のピック生成には一切影響しない
    （フェイルソフト）。`direction` はこのアーキテクチャでは常に quant 由来（`pick.direction`）
    のため、challenger の応答からは再導出しない。3 値は公式パイプラインと同じ
    `finalize_bracket` を必ず通し、サーバ側検証をバイパスさせない（CLAUDE.md 3 値必須検証）。
    複数プロバイダが設定されていれば並行して判定させる。
    """
    providers = resolve_shadow_providers("stock_pick")
    if not providers:
        return
    await asyncio.gather(*(_record_one_shadow_judgment(p, outcome, pick_id=pick_id) for p in providers))


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
    run_id: str | None = None,
    run_challenger: bool = False,
) -> InferenceOutcome:
    """1 銘柄ぶんの推論を stage DAG として実行し、トレースを記録しながらピック or 却下を返す.

    `rec`/`atr`/`trend_score` は呼び出し側（`pipeline.run_picks`）がショートリスト選定のために
    既に算出済みの値（collect/subscore/synthesis 相当）をそのまま受け取る — 二重計算しない。
    `run_id` 省略時は内部生成（既定、`pipeline.run_picks` からの通常呼び出し）。🆕 P36:
    `services/inference/sandbox.py` は事前生成した `run_id` を渡し、API が非同期タスク起動と
    同時に `run_id` を即座に返せるようにする（フロントはその `run_id` で SSE 購読を開始する）。
    🆕 `run_challenger=True`（`pipeline.run_picks` のみ）で、`PICK_PROMPT_CHALLENGER` が有効なら
    プロンプト挑戦者も同じ材料で判定し、採用分を `outcome.challenger_pick` に載せる（台帳化は呼び出し側）。
    sandbox は台帳化しないため挑戦者を呼ばない（既定 False）。
    """
    run_id = run_id or str(uuid.uuid4())
    recorder = _Recorder(run_id, symbol, horizon_type)

    # --- stage 1: collect ---
    tech = rec.get("technical_signals")
    current_price = num(tech.get("current_price")) if isinstance(tech, dict) else None
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
    # ニュース見出しLLMセンチメント（🆕、隔離LLM呼び出し）。shortlist後の1銘柄のみに掛けるため
    # コスト増は限定的。失敗・ニュース無しは None（フェイルソフト、ステージは失敗扱いにしない）。
    news_sentiment = await get_llm_news_sentiment(symbol)
    news_sentiment_block = render_news_sentiment_block(news_sentiment)
    # 🆕 P29: shortlist 選定後の判定を PIT 台帳へ副産物記録する（追加 LLM 呼び出しは発生しない、
    # `plans/03_システム設計` §3.7.7）。失敗してもピック生成本体には影響させない（フェイルソフト、
    # `record_llm_sentiment_snapshot` 内部で例外を握り潰す）。
    if news_sentiment is not None:
        await record_llm_sentiment_snapshot(symbol, news_sentiment)
    # 🆕 需給軸（週末信用取引残高）は中長期ピック限定（ユーザー指示）。短期は取得自体しない
    # （J-Quants 呼び出しコストを増やさないため、`news_sentiment` と違い horizon でゲートする）。
    supply_demand = await get_supply_demand_data(symbol) if horizon_type == "mid_term" else None
    supply_demand_block = render_supply_demand_block(supply_demand)
    if supply_demand is not None:
        await record_supply_demand_snapshot(symbol, supply_demand)
    # 🆕 決算サプライズ・予想修正モメンタムは需給軸と異なりホライズンによる gate なし
    # （短期・中長期の両方が対象、ニュースセンチメントと同じ扱い）。
    earnings_surprise = await get_earnings_surprise_data(symbol)
    earnings_surprise_block = render_earnings_surprise_block(earnings_surprise)
    if earnings_surprise is not None:
        await record_earnings_surprise_snapshot(symbol, earnings_surprise)

    def _build_prompt(variant: str) -> str:
        return build_pick_prompt(
            horizon_type=horizon_type,
            recommendation=rec,
            current_price=current_price,
            atr=atr,
            brand_frontmatter=brand.to_prompt_dict() if brand else None,
            news_digest_block=news_block,
            trend_context_block=trend_block,
            related_daily_frontmatter=related_daily or None,
            news_sentiment_block=news_sentiment_block,
            supply_demand_block=supply_demand_block,
            earnings_surprise_block=earnings_surprise_block,
            variant=variant,
        )

    ctx = JudgmentContext(
        symbol=symbol,
        horizon_type=horizon_type,
        batch_run_id=batch_run_id,
        issued_at=issued_at,
        rec=rec,
        atr=atr,
        trend_score=trend_score,
        gate_horizon=gate_horizon,
        current_price=current_price,
        brand=brand,
        news_sentiment=news_sentiment,
        supply_demand=supply_demand,
        earnings_surprise=earnings_surprise,
    )
    provider = resolve_feature_provider("stock_pick")
    prompt = _build_prompt("v1")
    # 挑戦者は公式の採否に関係なく判定させるため、公式の LLM 呼び出しより前に独立して実行する。
    challenger_pick = (
        await judge_with_challenger(
            ctx, provider=provider, build_prompt=_build_prompt, base_model_version=model_version
        )
        if run_challenger
        else None
    )

    try:
        raw = await provider.propose_stock_pick(ticker=symbol, prompt=prompt)
    except LLMError as e:
        rejected = RejectedPick(symbol=symbol, status="llm_error", reason=str(e))
        await recorder.emit("llm_overlay", "failed", {"error": str(e)}, run_status="rejected")
        return InferenceOutcome(
            run_id=run_id, symbol=symbol, status="rejected", rejected=rejected, challenger_pick=challenger_pick
        )

    # --- stage 4 後半〜6（llm_overlay の検証 → bracket → verify）は挑戦者と共通（`judgment.judge`）---
    result = await judge(ctx, raw, model_version=model_version, is_shadow=False, emitter=recorder)
    if result.pick is None:
        return InferenceOutcome(
            run_id=run_id, symbol=symbol, status="rejected", rejected=result.rejected, challenger_pick=challenger_pick
        )
    pick = result.pick
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
        challenger_pick=challenger_pick,
    )
