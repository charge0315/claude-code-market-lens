"""3 値ブラケット（推奨買値 / 損切値 / 推奨売値）の算出・クランプ・サーバ側検証.

Market Lens `backend/services/stock_pick_service.py` の `_atr_suggested_bracket` /
`_apply_atr_bracket` / `_validate_pick` / `_standardize_holding_period` を切り出して移植。
変更点（🔧）:
- フィールド名を Alpha Forge の `prediction_ledger` スキーマに合わせる
  （buy_price/stop_loss_price/take_profit_price → entry/stop/target）。
- LLM ピック（中長期）とデイトレピック（短期）の両方から共有する（`plans/01_PRD` §5.3）。

**サーバ側検証は必須**: `stop < 現在値 < target` かつ `stop < entry < target` かつ全て正値。
不整合は却下し、方向として妥当なブラケットのみ ATR ベースの許容レンジへクランプする
（CLAUDE.md「AI が売買銘柄を提案する全機能で 3 値を必須明記・サーバ側で検証」）。
"""

from __future__ import annotations

from dataclasses import dataclass

# ATR 倍率（プロンプトへ提示する目安）。
_SL_ATR_MULT = 1.5
_TP_ATR_MULT = 2.5
# 損切り / 利確の許容レンジ（現在値 ± ATR×min〜×max）。
_SL_ATR_MIN, _SL_ATR_MAX = 1.0, 3.0
_TP_ATR_MIN, _TP_ATR_MAX = 1.5, 4.0
# 買値は現在値の ATR×below 下〜×above 上（marketable な指値へ寄せる）。
_BUY_ATR_BELOW, _BUY_ATR_ABOVE = 0.1, 0.5
# 損切りは現在値からこの割合を超えて下げない（超高ボラ銘柄の保険）。
_MAX_SL_DROP_PCT = 0.5

# 想定保有期間（営業日）の許容レンジ。ML 予測ホライズン（5 営業日）と決着記録の垂直バリア
# （中長期 10 前後）に整合させる。
_MIN_HOLDING_DAYS = 5
_MAX_HOLDING_DAYS = 10
_DEFAULT_HOLDING_DAYS = 7


@dataclass(frozen=True)
class Bracket:
    """3 値ブラケット（すべて円、正値、`stop < entry < target`）."""

    entry: float
    stop: float
    target: float


def suggested_bracket(current_price: float, atr: float) -> dict[str, object]:
    """LLM プロンプトへ提示する ATR ベースの目安ブラケット."""
    return {
        "entry": round(current_price, 2),
        "stop": round(current_price - _SL_ATR_MULT * atr, 2),
        "target": round(current_price + _TP_ATR_MULT * atr, 2),
        "note": (
            f"買値は現在値付近、損切りは ATR×{_SL_ATR_MULT} 下・利確は ATR×{_TP_ATR_MULT} 上が目安。"
            f"損切りは現在値の ATR×{_SL_ATR_MIN}〜×{_SL_ATR_MAX} 下、"
            f"利確は ATR×{_TP_ATR_MIN}〜×{_TP_ATR_MAX} 上の範囲に収めること"
        ),
    }


def validate_bracket(current_price: float, entry: float, stop: float, target: float) -> str | None:
    """LLM が返した 3 値の内部矛盾を検査し、却下理由を返す（妥当なら None）.

    `stop < 現在値 < target` かつ `stop < entry < target` かつ全て正値。
    """
    if not (entry > 0 and stop > 0 and target > 0):
        return "非正の価格が含まれています"
    if stop >= current_price:
        return "損切り価格が現在値以上です"
    if target <= current_price:
        return "推奨売値が現在値以下です"
    if not (stop < entry < target):
        return "買値が損切り/利確レンジの外にあります"
    return None


def clamp_bracket(current_price: float, atr: float, entry: float, stop: float, target: float) -> Bracket:
    """方向として妥当なブラケットを ATR ベースの許容レンジへクランプする（atr > 0 前提）.

    クランプ後は必ず `stop < entry < target` かつ全て正値になる。
    """
    sl_far = current_price - _SL_ATR_MAX * atr
    sl_near = current_price - _SL_ATR_MIN * atr
    sl_positive_floor = current_price * (1.0 - _MAX_SL_DROP_PCT)
    clamped_stop = max(min(max(stop, sl_far), sl_near), sl_positive_floor)

    clamped_target = min(max(target, current_price + _TP_ATR_MIN * atr), current_price + _TP_ATR_MAX * atr)

    entry_low = current_price - _BUY_ATR_BELOW * atr
    entry_high = current_price + _BUY_ATR_ABOVE * atr
    clamped_entry = min(max(entry, entry_low), entry_high)
    # 超高ボラで floor が near を上回るケースでも entry が stop 以下 / target 以上に潰れないよう最終調整。
    span = clamped_target - clamped_stop
    clamped_entry = max(clamped_entry, clamped_stop + span * 0.05)
    clamped_entry = min(clamped_entry, clamped_target - span * 0.05)
    return Bracket(entry=clamped_entry, stop=clamped_stop, target=clamped_target)


def finalize_bracket(
    current_price: float,
    atr: float | None,
    raw_entry: float,
    raw_stop: float,
    raw_target: float,
) -> tuple[Bracket | None, str | None]:
    """検証 → クランプを 1 関数で行う。返り値は (Bracket, None) か (None, 却下理由).

    ATR が算出できない銘柄はクランプせず、検証を通った LLM 値をそのまま採用する。
    """
    reason = validate_bracket(current_price, raw_entry, raw_stop, raw_target)
    if reason is not None:
        return None, reason
    if atr is not None and atr > 0:
        return clamp_bracket(current_price, atr, raw_entry, raw_stop, raw_target), None
    return Bracket(entry=raw_entry, stop=raw_stop, target=raw_target), None


def standardize_holding_period(raw: object) -> int:
    """LLM が返す想定保有期間を許容レンジ [_MIN, _MAX] 営業日へ標準化する（不正は既定値）."""
    if not isinstance(raw, (int, float, str)):
        return _DEFAULT_HOLDING_DAYS
    try:
        days = int(raw)
    except (TypeError, ValueError):
        return _DEFAULT_HOLDING_DAYS
    return max(_MIN_HOLDING_DAYS, min(_MAX_HOLDING_DAYS, days))
