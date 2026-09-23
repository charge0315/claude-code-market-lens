"""テクニカル・ファンダメンタル・センチメント・ML 予測を統合した株式レコメンドサービス.

Market Lens `backend/services/recommender.py` から移植。変更点（🔧）:
- サブスコア算出を `scoring/subscores.py` へ分割（800 行超回避）。
- **ML 予測スコアを注入可能な provider に置き換え**（`MlScoreProvider`）。fresh な
  Alpha Forge には学習済みモデルが無いため既定は `null_ml_score`（常に `(None, None)`）。
  実 ML 予測（`ml_predictor` / `ensemble_predictor` + Alpha Forge の `model_registry`）は
  P5（継続学習ループ）で registry が埋まった時点で配線する。
- BUY/SELL 閾値の動的算出（Market Lens は `stock_pick_runs` 分布から導出）は、
  `prediction_ledger` にデータが貯まる P4 以降で配線する。当面は固定閾値。
- **`source_contributions`** を新規追加（各情報源が最終スコアへ寄与した度合い。CL-1）。
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Mapping
from dataclasses import dataclass

import pandas as pd

from backend.services.data.data_fetcher import get_stock_data
from backend.services.scoring.fundamental_analyzer import get_fundamental_data
from backend.services.scoring.sentiment_analyzer import get_news_sentiment
from backend.services.scoring.signal_scan_scoring import compute_composite
from backend.services.scoring.subscores import (
    as_float,
    compute_fundamental_score,
    compute_technical_score,
)

logger = logging.getLogger(__name__)

# 合成スコアの重み（Market Lens 準拠）。利用可能ファクターだけで再正規化する。
# `services/registry/factor_weight_service`（P5、shadow）が実測 IC との比較対象として参照するため public。
FACTOR_WEIGHTS: dict[str, float] = {
    "technical": 0.35,
    "ml_prediction": 0.20,
    "fundamental": 0.20,
    "sentiment": 0.10,
}

# 4 サブスコアの方向票しきい値。
_FACTOR_VOTE_UP = 55.0
_FACTOR_VOTE_DOWN = 45.0

# ML 予測スコア provider: (価格 DF, ticker) -> (score 0-100 | None, prediction_rate | None)。
MlScoreProvider = Callable[[pd.DataFrame, str], tuple[float | None, float | None]]


def null_ml_score(_df: pd.DataFrame, _ticker: str) -> tuple[float | None, float | None]:
    """学習済みモデルが無い前提の既定 provider（ML ファクターを合成へ入れない）."""
    return None, None


@dataclass(frozen=True)
class RecommenderThresholds:
    """BUY / SELL の合成スコア閾値（Market Lens の固定値を既定に）."""

    buy: float = 62.0
    sell: float = 38.0


DEFAULT_THRESHOLDS = RecommenderThresholds()


def _factor_vote(score: float | None) -> int:
    """サブスコアの方向票（+1 強気 / -1 弱気 / 0 中立・欠損）."""
    if score is None:
        return 0
    if score >= _FACTOR_VOTE_UP:
        return 1
    if score <= _FACTOR_VOTE_DOWN:
        return -1
    return 0


def _direction_concordance(scores: Mapping[str, float | None]) -> tuple[float, str]:
    """technical/ml_prediction/fundamental/sentiment の方向一致度と総合方向を返す.

    concordance = |利用可能ファクターの票合計| / 利用可能ファクター数（0.0〜1.0）。
    direction は bullish / bearish / neutral（全票 0）/ mixed（割れている）。
    """
    available = [s for s in scores.values() if s is not None]
    if not available:
        return 0.0, "neutral"
    votes = [_factor_vote(s) for s in available]
    total = sum(votes)
    concordance = round(abs(total) / len(available), 3)
    if total > 0:
        return concordance, "bullish"
    if total < 0:
        return concordance, "bearish"
    if all(v == 0 for v in votes):
        return concordance, "neutral"
    return concordance, "mixed"


def _source_contributions(scores: Mapping[str, float | None]) -> dict[str, dict[str, float]]:
    """各情報源（サブスコア）が合成スコアへ寄与した度合いを返す（CL-1 の source_contributions）.

    - weight_share: 利用可能ファクターだけで再正規化した後の重みシェア（合計 1.0）。
    - contribution: そのファクターが composite に足した点数（合計 ≈ composite）。
    - score: 元のサブスコア（0〜100）。
    """
    available = {k: float(v) for k in FACTOR_WEIGHTS if (v := scores.get(k)) is not None}
    if not available:
        return {}
    total_weight = sum(FACTOR_WEIGHTS[k] for k in available)
    out: dict[str, dict[str, float]] = {}
    for k, score in available.items():
        weight_share = FACTOR_WEIGHTS[k] / total_weight
        out[k] = {
            "weight_share": round(weight_share, 4),
            "contribution": round(weight_share * score, 2),
            "score": round(score, 1),
        }
    return out


def _build_reasoning(
    tech_details: Mapping[str, object],
    fund_details: Mapping[str, object],
    sentiment_avg: float,
    prediction_rate: float | None,
) -> list[str]:
    """サブスコアの内訳から推奨根拠テキスト（日本語）を組み立てる（Market Lens 準拠）."""
    reasoning: list[str] = []
    rsi = as_float(tech_details.get("rsi"))
    if rsi is not None:
        if rsi <= 30:
            reasoning.append(f"RSI {rsi:.1f} — 売られすぎ水準（30 以下）でリバウンドの可能性")
        elif rsi >= 70:
            reasoning.append(f"RSI {rsi:.1f} — 買われすぎ水準（70 以上）で調整リスク")

    if tech_details.get("macd_signal") == "buy":
        reasoning.append("MACD ゴールデンクロス — 上昇トレンドの初動シグナル")
    elif tech_details.get("macd_signal") == "sell":
        reasoning.append("MACD デッドクロス — 下降トレンドのシグナル")

    recent_cross = tech_details.get("recent_cross_event")
    if isinstance(recent_cross, Mapping):
        reasoning.append(f"{recent_cross.get('label')}（{recent_cross.get('days_ago')}営業日前、チャート兆候イベント）")

    per = as_float(fund_details.get("per"))
    if per is not None:
        if per < 15:
            reasoning.append(f"PER {per:.1f} 倍 — 業種平均比で割安水準")
        elif per > 35:
            reasoning.append(f"PER {per:.1f} 倍 — 高バリュエーションで調整余地あり")

    roe = as_float(fund_details.get("roe"))
    if roe is not None and roe > 0.10:
        reasoning.append(f"ROE {roe * 100:.1f}% — 高収益性を維持")

    if tech_details.get("signal_agreement") == "conflicting":
        reasoning.append("RSI・MACD・ボリンジャーバンドのシグナルが対立しており方向感が不明瞭")

    if fund_details.get("value_trap"):
        reasoning.append("ROE マイナス × PBR 3 倍超 — 収益性を欠いたまま株価が割高な「バリュートラップ」懸念")

    if sentiment_avg > 0.6:
        reasoning.append(f"センチメントスコア {sentiment_avg:.2f} — 市場心理はポジティブ")
    elif sentiment_avg < 0.4:
        reasoning.append(f"センチメントスコア {sentiment_avg:.2f} — 市場心理はネガティブ")

    if prediction_rate is not None:
        direction = "上昇" if prediction_rate > 0 else "下落"
        reasoning.append(f"ML 予測: 5 日後に {prediction_rate * 100:.2f}% {direction}と予測")

    if not reasoning:
        reasoning.append("総合スコアに基づく判定（個別シグナルは中立）")
    return reasoning


def compute_recommendation(
    ticker: str,
    *,
    fundamental: Mapping[str, object] | None = None,
    ml_score_provider: MlScoreProvider = null_ml_score,
    thresholds: RecommenderThresholds = DEFAULT_THRESHOLDS,
) -> dict[str, object]:
    """全指標を統合してレコメンドを生成する（同期）.

    Parameters
    ----------
    ticker: 銘柄コード（4 桁）
    fundamental: 事前取得済みのファンダメンタル指標（省略時は yfinance から取得）。
        ピック各サービス（P3d）は Vault frontmatter マージ済み（四季報スタブ期間の主経路）を渡す。
    ml_score_provider: ML 予測スコア provider（省略時は ML ファクターを合成に入れない）。
    thresholds: BUY / SELL 判定の合成スコア閾値。
    """
    df = get_stock_data(ticker, period="1y")
    fund = dict(fundamental) if fundamental is not None else get_fundamental_data(ticker)
    sentiment_data = get_news_sentiment(ticker, max_items=20)
    return recommend_from_inputs(
        ticker,
        df=df,
        fundamental=fund,
        sentiment=sentiment_data,
        ml_score_provider=ml_score_provider,
        thresholds=thresholds,
    )


def recommend_from_inputs(
    ticker: str,
    *,
    df: pd.DataFrame,
    fundamental: Mapping[str, object] | None,
    sentiment: Mapping[str, object] | None,
    ml_score_provider: MlScoreProvider = null_ml_score,
    thresholds: RecommenderThresholds = DEFAULT_THRESHOLDS,
) -> dict[str, object]:
    """取得済みの入力からレコメンドを生成する（I/O なし、🆕 P37 で `compute_recommendation` から分離）.

    過去日リプレイ（`services/replay/`）が「その日までの価格」だけを渡して同じ採点を再現するため、
    データ取得をここから切り離した。`fundamental` / `sentiment` が None の場合は、過去時点の値が
    残っていない（PIT 未収集）ことを意味するので、中立 50 で埋めずにファクターごと合成から外す。
    中立値で埋めると「常に 50 の定数ファクター」が合成スコアを 50 へ引き寄せ、実測 IC も歪むため。
    本番経路（`compute_recommendation`）は常に dict を渡すので挙動は変わらない。
    """
    fund: dict[str, object] = dict(fundamental) if fundamental is not None else {}
    tech_score, tech_details = compute_technical_score(df)
    fund_score: float | None = None
    fund_details: dict[str, object] = {}
    if fundamental is not None:
        fund_score, fund_details = compute_fundamental_score(fund)

    # ニュース 0 件のとき sentiment_analyzer は average_score=0.5（中立）を返すため、
    # そのまま採用すると常時定数 50 のファクターが混入する。total==0 は None 扱い。
    sentiment_avg = 0.5
    sentiment_score: float | None = None
    if sentiment is not None:
        avg = as_float(sentiment.get("average_score"))
        sentiment_avg = avg if avg is not None else 0.5
        total = as_float(sentiment.get("total"))
        if total is not None and total > 0:
            sentiment_score = sentiment_avg * 100.0

    ml_score, prediction_rate = ml_score_provider(df, ticker)

    scores: dict[str, float | None] = {
        "technical": tech_score,
        "ml_prediction": ml_score,
        "fundamental": fund_score,
        "sentiment": sentiment_score,
    }
    composite = compute_composite(scores, weights=FACTOR_WEIGHTS)
    # technical は常にスコアを返す設計のため composite が None になることは無い。
    composite = round(max(0.0, min(100.0, composite if composite is not None else 50.0)), 1)

    score_breakdown: dict[str, float | None] = {
        "technical": round(tech_score, 1),
        "ml_prediction": round(ml_score, 1) if ml_score is not None else None,
        "fundamental": round(fund_score, 1) if fund_score is not None else None,
        "sentiment": round(sentiment_score, 1) if sentiment_score is not None else None,
    }

    factor_concordance, factor_direction = _direction_concordance(scores)

    if composite >= thresholds.buy:
        recommendation = "BUY"
    elif composite <= thresholds.sell:
        recommendation = "SELL"
    else:
        recommendation = "HOLD"

    reasoning = _build_reasoning(tech_details, fund_details, sentiment_avg, prediction_rate)

    return {
        "ticker": ticker,
        "company_name": fund.get("company_name"),
        "recommendation": recommendation,
        "composite_score": composite,
        "concordance": factor_concordance,
        "direction": factor_direction,
        "score_breakdown": score_breakdown,
        "source_contributions": _source_contributions(scores),
        "technical_signals": {
            "rsi": tech_details.get("rsi"),
            "rsi_signal": tech_details.get("rsi_signal", "neutral"),
            "macd_signal": tech_details.get("macd_signal", "neutral"),
            "bb_signal": tech_details.get("bb_signal", "neutral"),
            "current_price": tech_details.get("current_price"),
            "signal_agreement": tech_details.get("signal_agreement", "neutral"),
            # 🆕 チャート（`/api/stock/{symbol}/ohlc`）のGC/DC・MACDクロスのマーカーと同じ検出結果。
            # `build_pick_prompt` がこの dict をそのまま JSON 化してLLMへ渡すため、ここに含めるだけで
            # 「チャートの兆候」がLLMの判断材料になる（ユーザー指示、追加のプロンプト変更は不要）。
            "recent_cross_event": tech_details.get("recent_cross_event"),
        },
        "fundamental_signals": fund_details,
        "sentiment_average": sentiment_avg,
        "ml_prediction_rate": prediction_rate,
        "reasoning": reasoning,
    }
