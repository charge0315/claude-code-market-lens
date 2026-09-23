"""過去日リプレイのピック選定（🆕 P37、LLM なし）.

本番パイプライン（`services/picks/pipeline.py` → `services/inference/orchestrator.py`）のうち、
LLM を使わない定量部分を同じ規則で再現する:

1. 候補プール: 本番と同じランキング規則（`ranking_service.rankings_from_bars` →
   `pipeline.order_candidate_codes`）。
2. 採点: `recommender.recommend_from_inputs`。価格は本番と同じく直近 1 年（テクニカル）と
   直近 3 か月（ATR・トレンド）。ファンダメンタル・センチメントは当時の値が無いので None
   （合成から除外）。
3. ショートリスト: 合成スコア降順に本番 `POOL_CONFIG` の件数。
4. ハード除外 E1（SELL 判定をロングに混ぜない）。E2（バリュートラップの確度上限）と E3（実測勝率
   ゲート）は LLM の確度に掛かる規則なので、LLM なしの第 1 段階では適用しない。
5. 3 値: LLM の代わりに ATR の目安ブラケット（`bracket.suggested_bracket`）を本番と同じ
   `finalize_bracket` で検証・クランプする（`損切 < 現在値 < 売値` かつ `損切 < 買値 < 売値`）。
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field

import pandas as pd

from backend.services.picks.bracket import finalize_bracket, suggested_bracket
from backend.services.picks.pipeline import POOL_CONFIG
from backend.services.replay.price_store import AsOfView
from backend.services.scoring.recommender import MlScoreProvider, recommend_from_inputs
from backend.services.scoring.signal_scan_scoring import compute_trend_score
from backend.services.scoring.technical_analysis import compute_atr

# 本番 `pipeline._ATR_PERIOD` と同じ。
_ATR_PERIOD = 14
# 本番のテクニカル採点に必要な最低限の行数（これ未満は指標が安定しないため採点しない）。
_MIN_ROWS = 60


@dataclass(frozen=True)
class ScoredCandidate:
    """候補プールの 1 銘柄ぶんの採点結果."""

    code: str
    rec: dict[str, object]
    atr: float | None
    trend_score: float | None
    close: float


@dataclass(frozen=True)
class ReplayPick:
    """リプレイで確定した 1 ピック（3 値必須）."""

    horizon_type: str
    symbol: str
    issued_at: str
    rank: int
    entry: float
    stop: float
    target: float
    close: float
    composite_score: float
    concordance: float | None
    direction: str | None
    recommendation: str | None
    trend_score: float | None
    ml_prediction_rate: float | None
    score_breakdown: dict[str, object] = field(default_factory=dict)
    source_contributions: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class RejectedCandidate:
    symbol: str
    reason: str


def _num(value: object) -> float | None:
    if isinstance(value, bool):
        return None
    return float(value) if isinstance(value, (int, float)) else None


def _window(df: pd.DataFrame, as_of: str, offset: pd.DateOffset) -> pd.DataFrame:
    return df[df.index > pd.Timestamp(as_of) - offset]


def score_candidates(view: AsOfView, codes: Sequence[str], provider: MlScoreProvider) -> list[ScoredCandidate]:
    """候補プールを採点する（履歴が足りない銘柄は静かにスキップ）."""
    out: list[ScoredCandidate] = []
    for code in codes:
        hist = view.history(code)
        df_1y = _window(hist, view.as_of, pd.DateOffset(years=1))
        if len(df_1y) < _MIN_ROWS:
            continue
        rec = recommend_from_inputs(code, df=df_1y, fundamental=None, sentiment=None, ml_score_provider=provider)
        df_3m = _window(hist, view.as_of, pd.DateOffset(months=3))
        atr = compute_atr(df_3m, _ATR_PERIOD)
        trend_score, _ = compute_trend_score(df_3m)
        out.append(
            ScoredCandidate(code=code, rec=rec, atr=atr, trend_score=trend_score, close=float(df_1y["Close"].iloc[-1]))
        )
    return out


def select_picks(
    candidates: Sequence[ScoredCandidate], horizon_type: str, *, issued_at: str
) -> tuple[list[ReplayPick], list[RejectedCandidate]]:
    """合成スコア順のショートリストから E1・3 値検証を通ったものを `max_picks` 件まで採用する."""
    cfg = POOL_CONFIG[horizon_type]
    ranked = sorted(candidates, key=lambda c: _num(c.rec.get("composite_score")) or 0.0, reverse=True)
    picks: list[ReplayPick] = []
    rejected: list[RejectedCandidate] = []
    for cand in ranked[: cfg["shortlist"]]:
        if len(picks) >= cfg["max_picks"]:
            break
        reason = _rejection_reason(cand)
        if reason is not None:
            rejected.append(RejectedCandidate(symbol=cand.code, reason=reason))
            continue
        pick = _to_pick(cand, horizon_type, issued_at, rank=len(picks) + 1)
        if pick is None:
            rejected.append(RejectedCandidate(symbol=cand.code, reason="3値ブラケットが不整合"))
            continue
        picks.append(pick)
    return picks, rejected


def _rejection_reason(cand: ScoredCandidate) -> str | None:
    if cand.rec.get("recommendation") == "SELL":
        return "E1: SELL判定"
    if cand.atr is None or cand.atr <= 0:
        return "ATRを算出できない"
    return None


def _to_pick(cand: ScoredCandidate, horizon_type: str, issued_at: str, *, rank: int) -> ReplayPick | None:
    atr = cand.atr if cand.atr is not None else 0.0
    guide = suggested_bracket(cand.close, atr)
    bracket, _reason = finalize_bracket(
        cand.close, atr, _num(guide["entry"]) or 0.0, _num(guide["stop"]) or 0.0, _num(guide["target"]) or 0.0
    )
    if bracket is None:
        return None
    rec = cand.rec
    breakdown = rec.get("score_breakdown")
    contributions = rec.get("source_contributions")
    return ReplayPick(
        horizon_type=horizon_type,
        symbol=cand.code,
        issued_at=issued_at,
        rank=rank,
        entry=round(bracket.entry, 2),
        stop=round(bracket.stop, 2),
        target=round(bracket.target, 2),
        close=cand.close,
        composite_score=_num(rec.get("composite_score")) or 0.0,
        concordance=_num(rec.get("concordance")),
        direction=str(rec["direction"]) if rec.get("direction") is not None else None,
        recommendation=str(rec["recommendation"]) if rec.get("recommendation") is not None else None,
        trend_score=cand.trend_score,
        ml_prediction_rate=_num(rec.get("ml_prediction_rate")),
        score_breakdown=dict(breakdown) if isinstance(breakdown, dict) else {},
        source_contributions=dict(contributions) if isinstance(contributions, dict) else {},
    )
