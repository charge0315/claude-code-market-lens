"""保有銘柄ごとの AI 売買タイミング判定（🆕 P7b、PF-3〜PF-5）.

Market Lens に対応物はない（`ai_portfolio_*` は別機能 — 自前資金で仮想ポートフォリオを
自律運用する仕組みであり、実保有への継続保有/一部利確/損切/買い増し判定ではない。
P7a のコミットログ参照）。3 値ブラケットの検証・クランプは `services/picks/bracket.py`
（P3d で確立済み）を再利用する。

判定は必ず `portfolio_signals` へ `status="proposed"` で記録するのみで、実際の売買判断・
発注は一切行わない（HITL、CLAUDE.md）。
"""

from __future__ import annotations

import asyncio
import logging

from backend.models.portfolio import PortfolioHolding
from backend.services.data.data_fetcher import get_stock_data
from backend.services.db.portfolio_signal_db import insert_signal
from backend.services.db.portfolio_signal_shadow_db import insert_shadow
from backend.services.llm.errors import LLMError
from backend.services.llm.provider import LLMProvider
from backend.services.llm.registry import resolve_feature_provider, resolve_shadow_providers
from backend.services.notify.notification_service import notify_signal
from backend.services.picks.bracket import Bracket, finalize_bracket
from backend.services.portfolio.portfolio_service import build_portfolio
from backend.services.portfolio.prompt import build_portfolio_signal_prompt
from backend.services.scoring.technical_analysis import compute_atr

logger = logging.getLogger(__name__)

_ATR_PERIOD = 14
_ATR_LOOKBACK = "3mo"
_VALID_ACTIONS = frozenset({"hold", "trim", "stop_loss", "add"})


def _num(value: object) -> float | None:
    if isinstance(value, bool):
        return None
    return float(value) if isinstance(value, (int, float)) else None


def _finalize_signal_bracket(
    action: str, current_price: float, atr: float | None, raw_entry: float, raw_stop: float, raw_target: float
) -> tuple[Bracket | None, str | None]:
    """action に応じて 3 値を検証・クランプする.

    `add`（新規買い増し）は通常のピックと同じ扱い（entry も検証対象）。それ以外
    （hold/trim/stop_loss）は既存ポジションの更新後 stop/target のみが対象で新規建ては無い。
    `entry` は永続化しないが、`finalize_bracket` の「entry は現在値付近」という制約を
    `current_price` を entry の代わりに渡すことで「stop < 現在値 < target」の検証へ流用する。
    """
    if action == "add":
        return finalize_bracket(current_price, atr, raw_entry, raw_stop, raw_target)
    return finalize_bracket(current_price, atr, current_price, raw_stop, raw_target)


async def _record_one_shadow_signal(
    provider: LLMProvider,
    *,
    signal_id: str,
    holding: PortfolioHolding,
    prompt: str,
    current_price: float,
    atr: float | None,
) -> None:
    """1 プロバイダぶんの shadow 判定を実行し `portfolio_signal_shadows` へ記録する（フェイルソフト）.

    AI ピックの `record_shadow_judgments`（`services/inference/orchestrator.py`）と同じ設計思想。
    承認・却下・実約定の判定フローには一切関与しない表示専用の記録のため、失敗しても本体の判定
    （`portfolio_signals` への記録）には影響させない。
    """
    pid = provider.provider_id
    try:
        raw = await provider.propose_portfolio_signal(symbol=holding.symbol, prompt=prompt)
    except LLMError as e:
        logger.warning("ポートフォリオ判定の %s shadow 呼び出しに失敗: %s (%s)", pid, holding.symbol, e)
        return

    raw_action = raw.get("action")
    if not isinstance(raw_action, str) or raw_action not in _VALID_ACTIONS:
        logger.warning("ポートフォリオ判定 %s shadow: 不正な action です: %s (%s)", pid, holding.symbol, raw_action)
        return
    action = raw_action

    raw_stop = _num(raw.get("stop_loss_price"))
    raw_target = _num(raw.get("take_profit_price"))
    confidence = _num(raw.get("confidence"))
    raw_entry = _num(raw.get("entry")) if action == "add" else current_price
    if raw_stop is None or raw_target is None or confidence is None or raw_entry is None:
        logger.warning("ポートフォリオ判定 %s shadow: 応答の数値形式が不正です: %s", pid, holding.symbol)
        return

    bracket, reason = _finalize_signal_bracket(action, current_price, atr, raw_entry, raw_stop, raw_target)
    if bracket is None:
        logger.info("ポートフォリオ判定 %s shadow 却下（3値不整合）: %s (%s)", pid, holding.symbol, reason)
        return

    try:
        await insert_shadow(
            signal_id=signal_id,
            challenger_version=f"{pid}:{provider.model_id}",
            action=action,
            entry=round(bracket.entry, 2) if action == "add" else None,
            stop=round(bracket.stop, 2),
            target=round(bracket.target, 2),
            confidence=confidence,
            reasoning=str(raw.get("reasoning") or "定量分析に基づく判定"),
        )
    except Exception:  # noqa: BLE001 — 表示専用の challenger 記録。失敗しても本体は継続する
        logger.warning("ポートフォリオ判定 %s shadow の記録に失敗しました: %s", pid, holding.symbol, exc_info=True)


async def _record_shadow_signals(
    *, signal_id: str, holding: PortfolioHolding, prompt: str, current_price: float, atr: float | None
) -> None:
    """設定された shadow プロバイダ群（0〜複数、`LLM_SHADOW_PROVIDERS_PORTFOLIO_SIGNAL`）に、
    公式パイプラインと同一のプロンプトを判定させ、比較参考用に記録する.
    """
    providers = resolve_shadow_providers("portfolio_signal")
    if not providers:
        return
    await asyncio.gather(
        *(
            _record_one_shadow_signal(
                p, signal_id=signal_id, holding=holding, prompt=prompt, current_price=current_price, atr=atr
            )
            for p in providers
        )
    )


async def evaluate_holding(holding: PortfolioHolding) -> str | None:
    """保有 1 ロットを LLM で評価し、判定を `portfolio_signals` へ記録する（提案のみ）.

    現在値が取得できない、LLM 呼び出しが失敗する、または応答が3値検証で却下される場合は
    何も記録せず None を返す（次回の監視サイクルで再評価される）。
    """
    if holding.current_price is None:
        logger.debug("ポートフォリオ判定スキップ（現在値未取得）: %s", holding.symbol)
        return None

    df = get_stock_data(holding.symbol, period=_ATR_LOOKBACK)
    atr = compute_atr(df, _ATR_PERIOD)

    prompt = build_portfolio_signal_prompt(
        symbol=holding.symbol,
        quantity=holding.quantity,
        avg_cost=holding.avg_cost,
        current_price=holding.current_price,
        unrealized_return_pct=holding.return_pct,
        atr=atr,
        company_name=holding.company_name,
        sector=holding.sector,
    )
    try:
        raw = await resolve_feature_provider("portfolio_signal").propose_portfolio_signal(
            symbol=holding.symbol, prompt=prompt
        )
    except LLMError as e:
        logger.warning("ポートフォリオ判定の LLM 呼び出しに失敗: %s (%s)", holding.symbol, e)
        return None

    raw_action = raw.get("action")
    if not isinstance(raw_action, str) or raw_action not in _VALID_ACTIONS:
        logger.warning("ポートフォリオ判定: 不正な action を受け取りました: %s (%s)", holding.symbol, raw_action)
        return None
    action = raw_action

    raw_stop = _num(raw.get("stop_loss_price"))
    raw_target = _num(raw.get("take_profit_price"))
    confidence = _num(raw.get("confidence"))
    raw_entry = _num(raw.get("entry")) if action == "add" else holding.current_price
    if raw_stop is None or raw_target is None or confidence is None or raw_entry is None:
        logger.warning("ポートフォリオ判定: 応答の数値形式が不正です: %s", holding.symbol)
        return None

    bracket, reason = _finalize_signal_bracket(action, holding.current_price, atr, raw_entry, raw_stop, raw_target)
    if bracket is None:
        logger.info("ポートフォリオ判定却下（3値不整合）: %s (%s)", holding.symbol, reason)
        return None

    entry = round(bracket.entry, 2) if action == "add" else None
    stop = round(bracket.stop, 2)
    target = round(bracket.target, 2)
    rationale = str(raw.get("reasoning") or "定量分析に基づく判定")
    signal_id = await insert_signal(
        symbol=holding.symbol,
        action=action,
        entry=entry,
        stop=stop,
        target=target,
        confidence=confidence,
        rationale=rationale,
    )
    await notify_signal(
        symbol=holding.symbol,
        action=action,
        stop=stop,
        target=target,
        confidence=confidence,
        rationale=rationale,
        entry=entry,
    )
    await _record_shadow_signals(
        signal_id=signal_id, holding=holding, prompt=prompt, current_price=holding.current_price, atr=atr
    )
    return signal_id


async def run_portfolio_monitor() -> list[str]:
    """全保有ロットを評価し、生成した `signal_id` の一覧を返す（celery-beat が場中に呼ぶ）."""
    summary = await build_portfolio()
    signal_ids: list[str] = []
    for holding in summary.holdings:
        signal_id = await evaluate_holding(holding)
        if signal_id is not None:
            signal_ids.append(signal_id)
    return signal_ids
