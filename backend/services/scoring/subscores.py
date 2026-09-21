"""テクニカル / ファンダメンタルのサブスコア算出（0〜100、中立 = 50）.

Market Lens `backend/services/recommender.py` の `_compute_technical_score` /
`_compute_fundamental_score` とその補助関数を切り出して移植（`recommender.py` の
800 行超を避けるための分割。ロジックは変更なし）。
"""

from __future__ import annotations

import logging
from collections.abc import Mapping

import pandas as pd

from backend.services.scoring.technical_analysis import (
    calculate_bollinger_bands,
    calculate_macd,
    calculate_rsi,
    detect_cross_events,
)

logger = logging.getLogger(__name__)

# RSI/MACD/BB の方向が食い違う場合のみ追加減点し、「シグナルが対立している」ことを
# スコアに反映させる（MACD 単体の重み ±12 の 8 割程度）。
_CONFLICT_PENALTY = 10.0

# チャート（`/api/stock/{symbol}/ohlc`）の GC/DC・MACDクロスのマーカーと同じ検出結果を
# LLM の判断材料（`recommendation.technical_signals`）にも反映する際の「直近」とみなす
# 営業日数の窓（🆕、ユーザー指示）。長すぎると鮮度の無い過去イベントまで拾ってしまう。
_RECENT_CROSS_EVENT_LOOKBACK_DAYS = 10

# ROE マイナス（収益性ゼロ以下）× PBR > 3 倍（資産価値の 3 倍超で購入）が同時成立する銘柄は
# 「バリュートラップ」（割安ではなく割高な不採算銘柄）とみなし追加減点する。
_VALUE_TRAP_PENALTY = 10.0
_VALUE_TRAP_PBR_THRESHOLD = 3.0


def as_float(value: object) -> float | None:
    """外部由来の object 値を float に絞り込む（数値以外や None は None）."""
    return float(value) if isinstance(value, (int, float)) else None


def _signal_vote(signal: str) -> int:
    """個別シグナル文字列を方向票（+1 買い / -1 売り / 0 中立）に変換する."""
    if signal in ("buy", "weak_buy"):
        return 1
    if signal in ("sell", "weak_sell"):
        return -1
    return 0


def signal_agreement(rsi_signal: str, macd_signal: str, bb_signal: str) -> str:
    """RSI/MACD/BB の 3 シグナルが同じ方向を向いているかを判定する.

    符号の異なる票が同時に存在する場合のみ "conflicting"。非ゼロ票がすべて同符号なら
    "aligned"、すべて 0 なら "neutral"。
    """
    votes = [_signal_vote(rsi_signal), _signal_vote(macd_signal), _signal_vote(bb_signal)]
    non_zero = [v for v in votes if v != 0]
    if not non_zero:
        return "neutral"
    if max(non_zero) > 0 and min(non_zero) < 0:
        return "conflicting"
    return "aligned"


def is_value_trap(roe: float | None, pbr: float | None) -> bool:
    """収益性マイナス（ROE<0）かつ資産価値超の割高（PBR>閾値）を同時に満たすかを判定する."""
    return roe is not None and roe < 0 and pbr is not None and pbr > _VALUE_TRAP_PBR_THRESHOLD


def _recent_cross_event(df: pd.DataFrame) -> dict[str, object] | None:
    """直近 `_RECENT_CROSS_EVENT_LOOKBACK_DAYS` 営業日以内に発生した兆候イベント（あれば最新の1件）を返す.

    UI のチャート（GC/DC・MACDクロスのマーカー、`detect_cross_events`）と同じ検出結果を、
    人間だけでなく LLM の判断材料にも使えるようにする（🆕、ユーザー指示）。
    """
    events = detect_cross_events(df)
    if not events:
        return None
    date_strs = [ts.isoformat()[:10] if hasattr(ts, "isoformat") else str(ts) for ts in df.index]
    latest = events[-1]
    try:
        days_ago = len(date_strs) - 1 - date_strs.index(latest["date"])
    except ValueError:
        return None
    if days_ago > _RECENT_CROSS_EVENT_LOOKBACK_DAYS:
        return None
    return {"kind": latest["kind"], "date": latest["date"], "days_ago": days_ago, "label": latest["label"]}


def compute_technical_score(df: pd.DataFrame) -> tuple[float, dict[str, object]]:
    """テクニカル指標から 0〜100 のスコアを算出する."""
    score = 50.0
    signals = {"rsi_signal": "neutral", "macd_signal": "neutral", "bb_signal": "neutral"}
    rsi_value: float | None = None

    if df.empty or len(df) < 30:
        return score, {
            **signals,
            "rsi": None,
            "current_price": None,
            "signal_agreement": "neutral",
            "recent_cross_event": None,
        }

    current_price = float(df["Close"].iloc[-1])

    try:
        rsi_series = calculate_rsi(df)
        rsi_value = next((r["value"] for r in reversed(rsi_series) if r["value"] is not None), None)
        if rsi_value is not None:
            if rsi_value <= 30:
                score += 25.0
                signals["rsi_signal"] = "buy"
            elif rsi_value <= 45:
                score += 10.0
                signals["rsi_signal"] = "weak_buy"
            elif rsi_value >= 70:
                score -= 25.0
                signals["rsi_signal"] = "sell"
            elif rsi_value >= 55:
                score -= 10.0
                signals["rsi_signal"] = "weak_sell"
    except Exception as e:  # noqa: BLE001 — 指標計算失敗は中立寄与にフォールバック
        logger.debug("RSI 計算エラー: %s", e)

    try:
        macd_data = calculate_macd(df)
        macd_vals = [v for r in macd_data["MACD"] if (v := r["value"]) is not None]
        sig_vals = [v for r in macd_data["Signal"] if (v := r["value"]) is not None]
        if macd_vals and sig_vals:
            if macd_vals[-1] > sig_vals[-1]:
                score += 12.0
                signals["macd_signal"] = "buy"
            else:
                score -= 12.0
                signals["macd_signal"] = "sell"
    except Exception as e:  # noqa: BLE001
        logger.debug("MACD 計算エラー: %s", e)

    try:
        bb_data = calculate_bollinger_bands(df)
        upper_vals = [v for r in bb_data["Upper"] if (v := r["value"]) is not None]
        lower_vals = [v for r in bb_data["Lower"] if (v := r["value"]) is not None]
        if upper_vals and lower_vals:
            upper = upper_vals[-1]
            lower = lower_vals[-1]
            band_width = upper - lower
            if band_width > 0:
                pos_in_band = (current_price - lower) / band_width
                if pos_in_band < 0.2:
                    score += 13.0
                    signals["bb_signal"] = "buy"
                elif pos_in_band > 0.8:
                    score -= 13.0
                    signals["bb_signal"] = "sell"
    except Exception as e:  # noqa: BLE001
        logger.debug("BB 計算エラー: %s", e)

    agreement = signal_agreement(signals["rsi_signal"], signals["macd_signal"], signals["bb_signal"])
    if agreement == "conflicting":
        score -= _CONFLICT_PENALTY

    recent_cross: dict[str, object] | None = None
    try:
        recent_cross = _recent_cross_event(df)
    except Exception as e:  # noqa: BLE001 — 検出失敗は「イベント無し」扱いにフォールバック
        logger.debug("兆候イベント検出エラー: %s", e)

    return max(0.0, min(100.0, score)), {
        **signals,
        "rsi": rsi_value,
        "current_price": current_price,
        "signal_agreement": agreement,
        "recent_cross_event": recent_cross,
    }


def compute_fundamental_score(fundamental: Mapping[str, object]) -> tuple[float, dict[str, object]]:
    """ファンダメンタル指標から 0〜100 のスコアを算出する."""
    score = 50.0

    per = as_float(fundamental.get("per"))
    pbr = as_float(fundamental.get("pbr"))
    roe = as_float(fundamental.get("roe"))
    dividend_yield = as_float(fundamental.get("dividend_yield"))

    if per is not None and per > 0:
        if per < 10:
            score += 15.0
        elif per < 15:
            score += 10.0
        elif per < 20:
            score += 5.0
        elif per > 40:
            score -= 15.0
        elif per > 30:
            score -= 8.0

    if pbr is not None and pbr > 0:
        if pbr < 0.8:
            score += 12.0
        elif pbr < 1.2:
            score += 6.0
        elif pbr > 3.0:
            score -= 8.0

    if roe is not None:
        if roe > 0.20:
            score += 15.0
        elif roe > 0.10:
            score += 8.0
        elif roe < 0:
            score -= 15.0

    if dividend_yield is not None and dividend_yield > 0:
        if dividend_yield > 0.03:
            score += 8.0
        elif dividend_yield > 0.01:
            score += 4.0

    value_trap = is_value_trap(roe, pbr)
    if value_trap:
        score -= _VALUE_TRAP_PENALTY

    return max(0.0, min(100.0, score)), {
        "per": per,
        "pbr": pbr,
        "roe": roe,
        "dividend_yield": dividend_yield,
        "value_trap": value_trap,
    }
