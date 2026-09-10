"""トリプルバリア・ラベリングの共通プリミティブ.

Market Lens `backend/services/labeling.py` から移植（変更なし）。
「エントリー後 H 営業日以内に、利確ラインに損切りラインより先に到達するか」を判定する
バリア走査ロジックを、決着記録（`services/ledger/` の P4 outcome resolution）と
継続学習の ML ラベル生成（P5）で共有する。

日次足では同一日内の高値・安値の前後関係が分からないため、同一日に損切り・利確の両方へ
触れた場合は **損切り優先**（保守的）とする。
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Literal

# Phase 1 相当のラベル生成が使う固定モデリング定数（ランタイムのブラケット倍率調整とは独立に pin する）。
LABEL_HORIZON_DAYS = 10  # 評価ホライズン（垂直バリア）
LABEL_K_SL_ATR = 1.5  # 損切りライン = エントリー − LABEL_K_SL_ATR × ATR
LABEL_K_TP_ATR = 2.5  # 利確ライン = エントリー + LABEL_K_TP_ATR × ATR

BarrierTouch = Literal["stop_loss", "take_profit"]


def first_barrier_touch(
    highs: Sequence[float],
    lows: Sequence[float],
    stop_loss: float,
    take_profit: float,
) -> tuple[int, BarrierTouch] | None:
    """高値 / 安値列を先頭から走査し、最初にどのバリアへ触れたか (index, 種別) を返す.

    どのバリアにも触れずに窓を走査し切った場合は None（＝時間切れ）。
    同一日に安値 ≤ stop_loss かつ 高値 ≥ take_profit の場合は損切り優先（保守的）。
    NaN の高値 / 安値は比較がすべて False になるため、その日は「未接触」として読み飛ばす。
    """
    for i, (high, low) in enumerate(zip(highs, lows, strict=True)):
        if low <= stop_loss:
            return i, "stop_loss"
        if high >= take_profit:
            return i, "take_profit"
    return None
