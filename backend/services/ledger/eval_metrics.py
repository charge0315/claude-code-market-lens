"""予測 / ピック評価に使う純粋関数群.

Market Lens `backend/services/eval_metrics.py` から移植（import パスのみ変更）。
I/O・DB・ネットワークを持たないため、価格データや学習済みモデルなしで単体テストできる。
継続学習の評価指標（CL-3: 較正 / IC / Brier / skill）で使う。
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np
from sklearn.metrics import brier_score_loss, roc_auc_score

from backend.services.ledger.skill_metrics import naive_rmse, skill_score

_DEFAULT_BOOTSTRAP_ITERATIONS = 1000
_DEFAULT_CONFIDENCE_LEVEL = 0.95


def clip_rate(values: Sequence[float], threshold: float) -> float:
    """|value| >= threshold を満たす割合を返す（空配列は 0.0）."""
    if not values:
        return 0.0
    arr = np.asarray(values, dtype=float)
    return float(np.mean(np.abs(arr) >= threshold))


def summary_percentiles(values: Sequence[float], ps: Sequence[float] = (10, 50, 90)) -> dict[str, float]:
    """指定パーセンタイル + min/max/stdev をまとめて返す（空配列は全て 0.0）."""
    if not values:
        return {"min": 0.0, "max": 0.0, "stdev": 0.0, **{f"p{int(p)}": 0.0 for p in ps}}
    arr = np.asarray(values, dtype=float)
    result: dict[str, float] = {
        "min": float(np.min(arr)),
        "max": float(np.max(arr)),
        "stdev": float(np.std(arr)),
    }
    for p in ps:
        result[f"p{int(p)}"] = float(np.percentile(arr, p))
    return result


def pearson_correlation(a: Sequence[float], b: Sequence[float]) -> float | None:
    """2 系列のピアソン相関係数を返す（データ不足・分散ゼロなら None）."""
    if len(a) != len(b) or len(a) < 2:
        return None
    arr_a = np.asarray(a, dtype=float)
    arr_b = np.asarray(b, dtype=float)
    if np.std(arr_a) == 0.0 or np.std(arr_b) == 0.0:
        return None
    corr = float(np.corrcoef(arr_a, arr_b)[0, 1])
    return corr if np.isfinite(corr) else None


def spearman_ic(scores: Sequence[float], forward_returns: Sequence[float]) -> float | None:
    """スコアと前方リターンの順位相関（IC = information coefficient）を返す.

    CL-3「ランキング有効性」の主指標。両系列を順位に変換してピアソン相関を取る
    （scipy 非依存の簡易 Spearman）。データ不足・分散ゼロなら None。
    """
    if len(scores) != len(forward_returns) or len(scores) < 3:
        return None
    s = np.asarray(scores, dtype=float)
    r = np.asarray(forward_returns, dtype=float)
    rank_s = s.argsort().argsort().astype(float)
    rank_r = r.argsort().argsort().astype(float)
    return pearson_correlation(rank_s.tolist(), rank_r.tolist())


def precision_at_k(scores: Sequence[float], wins: Sequence[float], k: int) -> float | None:
    """スコア上位 k 件の勝率（win∈{0,1}）を返す（CL-3「precision@k」）."""
    if len(scores) != len(wins) or len(scores) < k or k < 1:
        return None
    order = np.argsort(np.asarray(scores, dtype=float))[::-1][:k]
    top_wins = np.asarray(wins, dtype=float)[order]
    return float(np.mean(top_wins))


def directional_hit_rate(predicted: Sequence[float], actual: Sequence[float]) -> float | None:
    """予測と実測の符号が一致した割合を返す（データ不足なら None）."""
    if len(predicted) != len(actual) or len(predicted) == 0:
        return None
    pred_sign = np.sign(np.asarray(predicted, dtype=float))
    actual_sign = np.sign(np.asarray(actual, dtype=float))
    return float(np.mean(pred_sign == actual_sign))


@dataclass(frozen=True)
class SkillEstimate:
    """RMSE / ナイーブ RMSE / skill の点推定と、skill のブートストラップ信頼区間."""

    rmse: float
    naive_rmse: float
    skill: float
    skill_ci_lower: float
    skill_ci_upper: float
    sample_count: int


def evaluate_predictions(
    predicted: Sequence[float],
    actual: Sequence[float],
    *,
    bootstrap_iterations: int = _DEFAULT_BOOTSTRAP_ITERATIONS,
    confidence_level: float = _DEFAULT_CONFIDENCE_LEVEL,
    seed: int = 42,
) -> SkillEstimate | None:
    """(predicted, actual) のペア列から RMSE / skill とそのブートストラップ CI を算出する."""
    if len(predicted) != len(actual) or len(actual) < 2:
        return None

    pred_arr = np.asarray(predicted, dtype=float)
    actual_arr = np.asarray(actual, dtype=float)
    n = len(actual_arr)

    residual = pred_arr - actual_arr
    rmse = float(np.sqrt(np.mean(residual**2)))
    naive = naive_rmse(actual_arr)
    skill = skill_score(rmse, naive)

    rng = np.random.default_rng(seed)
    boot_skills = np.empty(bootstrap_iterations, dtype=float)
    for i in range(bootstrap_iterations):
        idx = rng.integers(0, n, size=n)
        boot_rmse = float(np.sqrt(np.mean((pred_arr[idx] - actual_arr[idx]) ** 2)))
        boot_skills[i] = skill_score(boot_rmse, naive_rmse(actual_arr[idx]))

    alpha = 1.0 - confidence_level
    lower = float(np.percentile(boot_skills, 100 * (alpha / 2)))
    upper = float(np.percentile(boot_skills, 100 * (1 - alpha / 2)))
    return SkillEstimate(rmse, naive, skill, lower, upper, n)


@dataclass(frozen=True)
class ClassificationEstimate:
    """トリプルバリア 2 値分類（勝率予測）の評価サマリ."""

    sample_count: int
    pos_rate: float
    auc: float | None
    brier: float
    brier_base: float
    brier_skill: float


def evaluate_classification(labels: Sequence[float], probabilities: Sequence[float]) -> ClassificationEstimate | None:
    """(label∈{0,1}, proba∈[0,1]) のペア列から AUC / Brier / base 比スキルを算出する."""
    if len(labels) != len(probabilities) or len(labels) < 2:
        return None

    y = np.asarray(labels, dtype=float)
    p = np.asarray(probabilities, dtype=float)
    n = len(y)
    pos_rate = float(np.mean(y))

    if 0.0 < pos_rate < 1.0:
        try:
            auc: float | None = float(roc_auc_score(y, p))
        except ValueError:
            auc = None
    else:
        auc = None

    brier = float(brier_score_loss(y, p))
    brier_base = float(np.mean((y - pos_rate) ** 2))
    brier_skill = 1.0 - brier / brier_base if brier_base > 0.0 else 0.0
    return ClassificationEstimate(n, pos_rate, auc, brier, brier_base, brier_skill)


def calibration_table(
    labels: Sequence[float], probabilities: Sequence[float], n_buckets: int = 5
) -> list[tuple[float, float, float, int]]:
    """予測確率を等間隔バケットに割り、各バケットの (下限, 平均予測確率, 実現勝率, 件数) を返す.

    較正曲線（予測 X% のとき実際に X% 勝てているか）を数値で確認する表。空バケットは含めない。
    """
    if len(labels) != len(probabilities) or not labels or n_buckets < 1:
        return []

    y = np.asarray(labels, dtype=float)
    p = np.clip(np.asarray(probabilities, dtype=float), 0.0, 1.0)
    edges = np.linspace(0.0, 1.0, n_buckets + 1)
    idx = np.clip(np.digitize(p, edges[1:-1], right=False), 0, n_buckets - 1)

    rows: list[tuple[float, float, float, int]] = []
    for b in range(n_buckets):
        mask = idx == b
        count = int(np.sum(mask))
        if count == 0:
            continue
        rows.append((float(edges[b]), float(np.mean(p[mask])), float(np.mean(y[mask])), count))
    return rows


@dataclass(frozen=True)
class DecileSpread:
    """スコア十分位ごとの実現リターンから、上位 − 下位のスプレッドを表す."""

    sample_count: int
    n_deciles: int
    top_mean: float
    bottom_mean: float
    spread: float


def decile_return_spread(scores: Sequence[float], returns: Sequence[float], n_deciles: int = 10) -> DecileSpread | None:
    """予測スコアで昇順ソートし n_deciles 分割、最上位と最下位の平均リターン差を返す."""
    if len(scores) != len(returns) or len(scores) < n_deciles or n_deciles < 2:
        return None

    order = np.argsort(np.asarray(scores, dtype=float), kind="stable")
    sorted_returns = np.asarray(returns, dtype=float)[order]
    buckets = np.array_split(sorted_returns, n_deciles)
    top_mean = float(np.mean(buckets[-1]))
    bottom_mean = float(np.mean(buckets[0]))
    return DecileSpread(len(scores), n_deciles, top_mean, bottom_mean, top_mean - bottom_mean)


def equity_curve(returns: Sequence[float], *, start: float = 1.0) -> list[float]:
    """勝敗確定順のリターン列（比率、例 0.03 = +3%）から累積エクイティ曲線を返す（CL-3）."""
    equity = start
    out: list[float] = []
    for r in returns:
        equity *= 1.0 + float(r)
        out.append(round(equity, 6))
    return out


def max_drawdown(equity: Sequence[float]) -> float:
    """エクイティ曲線の最大ドローダウン（正の比率、例 0.2 = 20% の下落）を返す."""
    if not equity:
        return 0.0
    peak = equity[0]
    worst = 0.0
    for v in equity:
        peak = max(peak, v)
        if peak > 0:
            worst = max(worst, (peak - v) / peak)
    return round(worst, 6)


def sharpe_ratio(returns: Sequence[float], *, periods_per_year: int = 252) -> float | None:
    """リターン列の年率換算シャープレシオ（リスクフリー 0 前提）。分散ゼロ・少数なら None."""
    if len(returns) < 2:
        return None
    arr = np.asarray(returns, dtype=float)
    sd = float(np.std(arr, ddof=1))
    if sd == 0.0:
        return None
    return float(np.mean(arr) / sd * np.sqrt(periods_per_year))
