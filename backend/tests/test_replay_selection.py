"""過去日リプレイのピック選定（🆕 P37、LLM なし）の検証."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from backend.services.replay import price_store as ps
from backend.services.replay import selection as sel
from backend.services.scoring.recommender import null_ml_score


def _store() -> tuple[ps.PriceStore, list[str]]:
    dates = [d.strftime("%Y-%m-%d") for d in pd.bdate_range("2021-01-04", periods=300)]
    rows: list[dict[str, object]] = []
    for i, trend in enumerate((0.004, 0.0, -0.004)):
        code = f"{1000 + i}0"
        closes = 1000.0 * np.exp(np.cumsum(np.full(len(dates), trend)) + np.sin(np.arange(len(dates)) / 3) * 0.01)
        for d, c in zip(dates, closes, strict=True):
            rows.append(
                {"Date": d, "Code": code, "AdjO": c, "AdjH": c * 1.02, "AdjL": c * 0.98, "AdjC": c, "AdjVo": 1e5}
            )
    return ps.PriceStore(pd.DataFrame(rows)), dates


def test_score_candidates_uses_only_one_year_of_history_up_to_as_of() -> None:
    store, dates = _store()
    view = store.view(dates[280])

    cands = sel.score_candidates(view, ["1000", "1001", "9999"], null_ml_score)

    assert [c.code for c in cands] == ["1000", "1001"]  # 履歴の無い銘柄はスキップ
    first = cands[0]
    assert first.close == pytest.approx(view.history("1000")["Close"].iloc[-1])
    assert first.atr is not None and first.atr > 0
    breakdown = first.rec["score_breakdown"]
    assert isinstance(breakdown, dict)
    assert breakdown["fundamental"] is None and breakdown["sentiment"] is None


def _cand(code: str, composite: float, recommendation: str = "HOLD", atr: float | None = 10.0) -> sel.ScoredCandidate:
    rec: dict[str, object] = {
        "composite_score": composite,
        "recommendation": recommendation,
        "direction": "bullish",
        "concordance": 1.0,
        "score_breakdown": {"technical": composite},
        "source_contributions": {"technical": {"score": composite}},
        "ml_prediction_rate": None,
    }
    return sel.ScoredCandidate(code=code, rec=rec, atr=atr, trend_score=50.0, close=1000.0)


def test_select_picks_shortlists_by_composite_and_applies_e1_and_bracket_rules() -> None:
    cands = [
        _cand("1111", 70.0),
        _cand("2222", 30.0, recommendation="SELL"),
        _cand("3333", 80.0, recommendation="SELL"),  # 上位だが E1（SELL 判定をロングに混ぜない）で除外
        _cand("4444", 60.0, atr=None),  # ATR 不明 → 3 値を決められないので除外
        _cand("5555", 50.0),
    ]

    picks, rejected = sel.select_picks(cands, "short_term", issued_at="2021-12-01")

    assert [p.symbol for p in picks] == ["1111", "5555"]
    assert {r.symbol for r in rejected} == {"3333", "4444", "2222"}
    top = picks[0]
    assert top.stop < top.entry < top.target
    assert top.stop < 1000.0 < top.target  # 損切 < 現在値 < 売値
    assert top.rank == 1 and picks[1].rank == 2
    assert top.issued_at == "2021-12-01"


def test_select_picks_respects_shortlist_and_max_picks() -> None:
    cands = [_cand(f"{1000 + i}", 90.0 - i) for i in range(20)]

    picks, _ = sel.select_picks(cands, "short_term", issued_at="2021-12-01")

    # 短期: shortlist 8 → max_picks 6（本番 POOL_CONFIG と同じ）
    assert len(picks) == 6
    assert [p.symbol for p in picks] == [f"{1000 + i}" for i in range(6)]
