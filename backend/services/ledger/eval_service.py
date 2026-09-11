"""評価指標の集計と永続化（CL-3）.

決着済みピック（`prediction_ledger` + `pick_outcomes`）から:
- 確度較正曲線（予測確度バケット → 実測勝率）+ Brier
- ランキング有効性（IC = composite_score と前方 excess の順位相関、precision@k）
- ピックポートフォリオ成績（勝率・平均 R 倍数・期待値・最大 DD・Sharpe、excess ベース）
を算出し、`eval_snapshots` / `calibration_curves` へ時系列で追記する（成長曲線用）。

確度較正（isotonic / Platt、CL-7 / N3）はここで **学習** する（`confidence_raw` → `win`）。
学習した較正器は `services/registry/calibration` が永続化し、ピック生成時（軽量・同期）に
適用する。台帳が薄いうちは `calibration.fit_and_save` が identity へフォールバックするため
`is_calibrated=False` のままになる。
"""

from __future__ import annotations

import logging

from backend.services.db import eval_db, pick_outcome_db
from backend.services.ledger import eval_metrics as em
from backend.services.registry import calibration

logger = logging.getLogger(__name__)

# scope（mid_term / short_term / combined）ごとの評価ホライズン。
_SCOPE_HORIZONS: dict[str, tuple[int, ...]] = {
    "mid_term": (5, 20, 60),
    "short_term": (1, 2, 3),
}
_PRECISION_K = 5


def _f(value: object) -> float:
    """DB 行の object 値を float へ（非数値は 0.0）."""
    return float(value) if isinstance(value, (int, float)) else 0.0


def _r_multiple(realized: float, entry: float, stop: float) -> float | None:
    """R 倍数 = 実現リターン / 1R（1R = 損切り幅の比率）。損切り幅が非正なら None."""
    risk = (entry - stop) / entry if entry else 0.0
    return realized / risk if risk > 0 else None


async def compute_and_persist(*, scope: str, horizon_days: int) -> dict[str, float | None]:
    """1 つの (scope, horizon_days) について評価指標を算出し永続化する。返り値は算出値の要約."""
    horizon_type = None if scope == "combined" else scope
    rows = await pick_outcome_db.list_resolved_for_eval(horizon_days=horizon_days)
    if horizon_type is not None:
        rows = [r for r in rows if r["horizon_type"] == horizon_type]

    n = len(rows)
    if n < 3:
        logger.info("評価: scope=%s horizon=%d はサンプル %d 件で不足（スキップ）", scope, horizon_days, n)
        return {"sample_n": float(n)}

    wins = [1.0 if r["win"] else 0.0 for r in rows]
    excess = [_f(r["excess_return"]) for r in rows]
    realized = [_f(r["realized_return"]) for r in rows]
    composite = [_f(r["composite_score"]) for r in rows]
    confidence_raw = [_f(r["confidence_raw"]) for r in rows]
    probs = [c / 100.0 for c in confidence_raw]

    win_rate = round(sum(wins) / n, 4)
    ic = em.spearman_ic(composite, excess)
    prec_k = em.precision_at_k(composite, wins, _PRECISION_K)
    cls = em.evaluate_classification(wins, probs)
    brier = cls.brier if cls else None
    auc = cls.auc if cls else None

    r_multiples = [
        rm for r in rows if (rm := _r_multiple(_f(r["realized_return"]), _f(r["entry"]), _f(r["stop"]))) is not None
    ]
    avg_r = round(sum(r_multiples) / len(r_multiples), 4) if r_multiples else None
    expectancy = round(sum(realized) / n, 6)
    eq = em.equity_curve(excess)
    max_dd = em.max_drawdown(eq)
    sharpe = em.sharpe_ratio(realized)

    metrics: dict[str, float | None] = {
        "win_rate": win_rate,
        "ic": round(ic, 4) if ic is not None else None,
        "precision_at_k": round(prec_k, 4) if prec_k is not None else None,
        "brier": round(brier, 6) if brier is not None else None,
        "auc": round(auc, 4) if auc is not None else None,
        "avg_r_multiple": avg_r,
        "expectancy": expectancy,
        "max_dd": max_dd,
        "sharpe": round(sharpe, 4) if sharpe is not None else None,
    }
    for name, value in metrics.items():
        if value is not None:
            await eval_db.insert_eval_snapshot(
                scope=scope,
                metric_name=name,
                metric_value=value,
                sample_n=n,
                horizon_days=horizon_days,
            )

    # 較正曲線（予測確度バケット → 実測勝率）。
    table = em.calibration_table(wins, probs, n_buckets=5)
    points = [{"p_pred": round(mean_p, 4), "p_obs": round(obs, 4), "n": float(cnt)} for _lo, mean_p, obs, cnt in table]

    # 較正器の学習（identity/isotonic/platt は confidence_raw の件数から自動選択、CL-7）。
    method = calibration.fit_and_save(scope, horizon_days, confidence_raw, [bool(w) for w in wins])

    await eval_db.upsert_calibration_curve(
        scope=scope,
        points=points,
        brier=round(brier, 6) if brier is not None else None,
        is_calibrated=(method != "identity"),
        horizon_days=horizon_days,
    )

    metrics["sample_n"] = float(n)
    return metrics


async def run_eval_batch() -> dict[str, dict[str, float | None]]:
    """全 scope × 主要ホライズンの評価指標を算出・永続化する（celery-beat が夜間に呼ぶ）."""
    out: dict[str, dict[str, float | None]] = {}
    for scope, horizons in (("mid_term", _SCOPE_HORIZONS["mid_term"]), ("short_term", _SCOPE_HORIZONS["short_term"])):
        for h in horizons:
            out[f"{scope}:{h}"] = await compute_and_persist(scope=scope, horizon_days=h)
    # combined は代表ホライズン（中長期 20 / 短期 3）だけ集計する。
    for h in (3, 20):
        out[f"combined:{h}"] = await compute_and_persist(scope="combined", horizon_days=h)
    return out
