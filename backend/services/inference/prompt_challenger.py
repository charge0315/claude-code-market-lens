"""AIピック判定プロンプトの挑戦者（challenger）を公式と並走させる.

PRD CL-6 の「challenger は shadow 推論で本番と並走し、実測で champion を上回れば昇格を提案」を、
プロンプトの版（`picks/prompt.py` の PROMPT_VARIANTS）について実装したもの。

- **同じモデル・同じ材料**で、冒頭の役割・判断基準だけ違うプロンプトを判定させる
  （違いをプロンプトの効果として測るため。プロバイダは公式が解決したものをそのまま受け取る）。
- 公式の採否に関係なく判定する（公式が見送った銘柄を挑戦者が採る／その逆、の両方を実測するため）。
- 検証・ゲートは公式と同じ `judgment.judge` を通す。採用分は `is_shadow=1`・
  `model_version="<公式版>+<挑戦者の版>"` で台帳化され、決着後に昇格評価だけが読む
  （公式の一覧・通知・note・確度較正・E3 ゲートには混ざらない。`test_shadow_ledger_isolation.py`）。
- トレースは書かない（銘柄詳細の AI 思考表示を公式判定だけにするため）。
- 失敗は握り潰す（フェイルソフト）。公式ピックの生成を絶対に止めない。
"""

from __future__ import annotations

import logging
from collections.abc import Callable

from backend.config import settings
from backend.models.pick import LedgerEntry
from backend.services.inference.judgment import JudgmentContext, judge
from backend.services.llm.errors import LLMError
from backend.services.llm.provider import LLMProvider
from backend.services.picks.prompt import PROMPT_VARIANTS

logger = logging.getLogger(__name__)

_CHAMPION_VARIANT = "v1"


def active_variant() -> str | None:
    """有効な挑戦者の版を返す（未設定・champion と同じ版・未知の版なら None = 無効）."""
    variant = settings.pick_prompt_challenger.strip()
    if not variant or variant == _CHAMPION_VARIANT:
        return None
    if variant not in PROMPT_VARIANTS:
        logger.warning("PICK_PROMPT_CHALLENGER=%s は未知のプロンプト版のため挑戦者を無効にします", variant)
        return None
    return variant


def challenger_model_version(base_model_version: str, variant: str) -> str:
    """挑戦者の版を台帳・モデルレジストリで区別するためのバージョン名."""
    return f"{base_model_version}+{variant}"


async def judge_with_challenger(
    ctx: JudgmentContext,
    *,
    provider: LLMProvider,
    build_prompt: Callable[[str], str],
    base_model_version: str,
) -> LedgerEntry | None:
    """挑戦者のプロンプトで 1 銘柄を判定し、採用なら `is_shadow=True` の台帳行を返す（無効・不採用・失敗は None）."""
    variant = active_variant()
    if variant is None:
        return None
    try:
        raw = await provider.propose_stock_pick(ticker=ctx.symbol, prompt=build_prompt(variant))
        result = await judge(
            ctx,
            raw,
            model_version=challenger_model_version(base_model_version, variant),
            is_shadow=True,
            emitter=None,
        )
    except LLMError as e:
        logger.warning("プロンプト挑戦者 %s の判定に失敗しました（%s）: %s", variant, ctx.symbol, e)
        return None
    except Exception:  # noqa: BLE001 — 挑戦者は比較用。どんな失敗でも公式ピックの生成を止めない
        logger.warning("プロンプト挑戦者 %s の判定で想定外のエラー（%s）", variant, ctx.symbol, exc_info=True)
        return None
    if result.rejected is not None:
        logger.info("プロンプト挑戦者 %s は %s を見送り: %s", variant, ctx.symbol, result.rejected.reason)
    return result.pick
