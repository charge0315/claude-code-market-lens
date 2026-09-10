"""シグナルスコアリング・集計のコアロジック（純粋関数群）.

Market Lens `backend/services/signal_scan_scoring.py` から移植（import パスのみ変更）。
I/O・DB・非同期を持たないため素の値だけで単体テストできる。`recommender` と
`signal_scan_*`（P3e）が共有する。スコアはいずれも 0〜100（中立 = 50）スケール。
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Final

import pandas as pd

from backend.services.scoring.technical_analysis import calculate_sma

# 合成スコアの重み（ML 予測は含めない：全銘柄のうちモデルがあるのは一部だけで合成が
# 銘柄間で非対称になり、コストも跳ね上がるため）。sentiment は yfinance が日本株ニュースを
# ほとんど返さず「常に定数 50」のファクター混入になるため除外（列は将来の日本語ニュース源に備え残す）。
FACTOR_WEIGHTS: Final[dict[str, float]] = {
    "technical": 0.40,
    "trend": 0.30,
    "fundamental": 0.30,
}
FACTOR_NAMES: Final[tuple[str, ...]] = ("technical", "trend", "fundamental")

_NEUTRAL_SCORE: Final[float] = 50.0
_VOTE_UP_THRESHOLD: Final[float] = 55.0
_VOTE_DOWN_THRESHOLD: Final[float] = 45.0

# trend ファクター
_TREND_LOOKBACK_ROWS: Final[int] = 60  # 約 12 週
_TREND_RETURN_FULL_SCALE: Final[float] = 0.20  # ±20% リターンで ±25 点に飽和
_TREND_RETURN_POINTS: Final[float] = 25.0
_TREND_SMA_POINTS: Final[float] = 10.0
_TREND_SLOPE_ROWS: Final[int] = 20
_TREND_SLOPE_POINTS: Final[float] = 5.0

# confidence
_FULL_HISTORY_ROWS: Final[int] = 250  # 日足 1 年分で価格データ満点
_FUNDAMENTAL_FIELD_COUNT: Final[int] = 4  # per / pbr / roe / dividend_yield

_HISTOGRAM_BIN_COUNT: Final[int] = 10
_HISTOGRAM_BIN_WIDTH: Final[float] = 100.0 / _HISTOGRAM_BIN_COUNT


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def compute_trend_score(df: pd.DataFrame) -> tuple[float | None, dict[str, float | str | None]]:
    """価格 DF から 0〜100 の per-stock トレンド / モメンタムスコアを算出する.

    technical ファクターが必要とするのと同じ価格 DF だけで完結し、追加の API 呼び出しは無い。
    十分な履歴（`_TREND_LOOKBACK_ROWS + 1` 行）が無ければ `(None, {})` を返す。
    """
    if df.empty or "Close" not in df.columns or len(df) < _TREND_LOOKBACK_ROWS + 1:
        return None, {}

    close = df["Close"].astype(float)
    last = float(close.iloc[-1])
    base = float(close.iloc[-(_TREND_LOOKBACK_ROWS + 1)])
    return_60d = (last / base - 1.0) if base else 0.0

    score = _NEUTRAL_SCORE
    score += _clamp(return_60d / _TREND_RETURN_FULL_SCALE, -1.0, 1.0) * _TREND_RETURN_POINTS

    sma = calculate_sma(df, [50, 200])
    sma50 = _last_value(sma.get("SMA_50", []))
    sma200 = _last_value(sma.get("SMA_200", []))
    vs_sma50 = _sma_side(last, sma50)
    vs_sma200 = _sma_side(last, sma200)
    if vs_sma50 is not None:
        score += _TREND_SMA_POINTS if vs_sma50 else -_TREND_SMA_POINTS
    if vs_sma200 is not None:
        score += _TREND_SMA_POINTS if vs_sma200 else -_TREND_SMA_POINTS

    slope_up: bool | None = None
    if len(close) >= _TREND_SLOPE_ROWS + 1:
        slope_up = float(close.iloc[-1]) > float(close.iloc[-(_TREND_SLOPE_ROWS + 1)])
        score += _TREND_SLOPE_POINTS if slope_up else -_TREND_SLOPE_POINTS

    detail: dict[str, float | str | None] = {
        "return_60d": round(return_60d, 4),
        "vs_sma50": _tri_state(vs_sma50),
        "vs_sma200": _tri_state(vs_sma200),
        "price_up_20d": _tri_state(slope_up),
    }
    return round(_clamp(score, 0.0, 100.0), 1), detail


def _last_value(records: Sequence[Mapping[str, object]]) -> float | None:
    """calculate_sma の [{date, value}] レコード列から末尾の非 None 値を返す."""
    for record in reversed(records):
        value = record.get("value")
        if isinstance(value, (int, float)):
            return float(value)
    return None


def _sma_side(price: float, sma: float | None) -> bool | None:
    """price が sma を上回っていれば True、下回っていれば False、sma が無ければ None."""
    if sma is None:
        return None
    return price > sma


def _tri_state(value: bool | None) -> str | None:
    if value is None:
        return None
    return "above" if value else "below"


def factor_vote(score: float | None) -> int:
    """スコアの方向票（+1 強気 / -1 弱気 / 0 中立・欠損）."""
    if score is None:
        return 0
    if score >= _VOTE_UP_THRESHOLD:
        return 1
    if score <= _VOTE_DOWN_THRESHOLD:
        return -1
    return 0


def factor_votes(scores: Mapping[str, float | None]) -> dict[str, int]:
    """各ファクターの方向票を返す（欠損は 0）."""
    return {name: factor_vote(scores.get(name)) for name in FACTOR_NAMES}


def compute_concordance(scores: Mapping[str, float | None]) -> tuple[float | None, str]:
    """ファクターの方向一致度と総合方向を返す.

    concordance = |利用可能ファクターの方向票の合計| / 利用可能ファクター数（0.0〜1.0）。
    中立票は「合意ではない」ため concordance を下げる（意図的な設計）。
    """
    available = [scores.get(name) for name in FACTOR_NAMES if scores.get(name) is not None]
    if not available:
        return None, "neutral"

    votes = [factor_vote(s) for s in available]
    total = sum(votes)
    concordance = abs(total) / len(available)

    if total > 0:
        direction = "bullish"
    elif total < 0:
        direction = "bearish"
    elif all(v == 0 for v in votes):
        direction = "neutral"
    else:
        direction = "mixed"

    return round(concordance, 3), direction


def compute_composite(scores: Mapping[str, float | None], weights: Mapping[str, float] | None = None) -> float | None:
    """利用可能なファクターだけで重みを再正規化した合成スコアを返す.

    weights 省略時は FACTOR_WEIGHTS。`recommender` はファクター構成が異なるため
    呼び出し側で別の重み辞書を渡せるようにしている（DRY 化）。
    """
    factor_weights = weights if weights is not None else FACTOR_WEIGHTS
    available: dict[str, float] = {k: float(v) for k in factor_weights if (v := scores.get(k)) is not None}
    if not available:
        return None
    total_weight = sum(factor_weights[k] for k in available)
    weighted = sum(v * factor_weights[k] for k, v in available.items())
    return round(weighted / total_weight, 1)


def compute_data_completeness(scores: Mapping[str, float | None]) -> float:
    """ファクター中いくつのスコアが得られたか（0.0〜1.0）."""
    available = sum(1 for name in FACTOR_NAMES if scores.get(name) is not None)
    return round(available / len(FACTOR_NAMES), 2)


def compute_confidence(*, data_completeness: float, price_rows: int, fundamental_field_count: int) -> float:
    """データの厚みからシグナルの信頼度（0.0〜1.0）を算出する."""
    price_factor = min(price_rows / _FULL_HISTORY_ROWS, 1.0)
    fund_factor = min(fundamental_field_count / _FUNDAMENTAL_FIELD_COUNT, 1.0)
    confidence = 0.5 * data_completeness + 0.3 * price_factor + 0.2 * fund_factor
    return round(confidence, 3)


def classify_status(scores: Mapping[str, float | None]) -> str:
    """取得できたファクター数から状態を分類する（全 → ok / 一部 → partial / 0 → failed）."""
    available = sum(1 for name in FACTOR_NAMES if scores.get(name) is not None)
    if available == len(FACTOR_NAMES):
        return "ok"
    if available == 0:
        return "failed"
    return "partial"


def histogram(values: Sequence[float]) -> list[tuple[float, float, int]]:
    """0-100 を 10 点刻みの固定 10 ビンに割り当てて (lower, upper, count) を返す."""
    counts = [0] * _HISTOGRAM_BIN_COUNT
    for raw in values:
        idx = int(raw // _HISTOGRAM_BIN_WIDTH)
        idx = max(0, min(_HISTOGRAM_BIN_COUNT - 1, idx))
        counts[idx] += 1
    return [(i * _HISTOGRAM_BIN_WIDTH, (i + 1) * _HISTOGRAM_BIN_WIDTH, counts[i]) for i in range(_HISTOGRAM_BIN_COUNT)]
