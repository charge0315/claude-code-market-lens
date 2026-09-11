"""特徴量分布ドリフト検知（PSI）— CL-4 / N5.

`plans/03_システム設計` §3.4。ベースライン期間（学習・過去データ）と直近期間の特徴量分布の
ずれを Population Stability Index（PSI）で定量化する。PSI はベースラインの十分位ビンに
直近データを割り当て、ビンごとの構成比の乖離を測る（分布形状に依存しない一般的な指標）。

閾値（既定 0.2）を超える特徴量が現れたら `drift_flag=True` を記録する。実際の追加再学習
（`triggered_retrain`）のディスパッチは、ML predictor スタック（xgboost、P5 の後続フェーズ）
が入ってから配線する。現時点ではモニタリング（記録のみ）として機能する。
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from backend.config import settings
from backend.services.db import drift_db
from backend.services.ledger import prediction_ledger as pl

_MIN_SAMPLES_PER_WINDOW = 20
_DEFAULT_BINS = 10
_EPS = 1e-6

# ドリフト監視の対象特徴量（`feature_snapshot` の dotted path）。
MONITORED_FEATURES: tuple[str, ...] = (
    "score_breakdown.technical",
    "score_breakdown.fundamental",
    "atr_14",
    "trend_score",
)


@dataclass(frozen=True)
class DriftResult:
    """1 特徴量分の PSI 計測結果."""

    feature_name: str
    psi: float
    drift_flag: bool
    baseline_n: int
    current_n: int


def compute_psi(baseline: list[float], current: list[float], n_bins: int = _DEFAULT_BINS) -> float | None:
    """ベースライン分布の十分位ビンを基準に PSI を計算する（サンプル不足なら None）.

    PSI = Σ (current_pct - baseline_pct) * ln(current_pct / baseline_pct)（ビンごと）。
    0 除算を避けるため各ビン構成比に `_EPS` を加える。
    """
    if len(baseline) < _MIN_SAMPLES_PER_WINDOW or len(current) < _MIN_SAMPLES_PER_WINDOW:
        return None

    base = np.asarray(baseline, dtype=float)
    curr = np.asarray(current, dtype=float)

    quantiles = np.linspace(0.0, 1.0, n_bins + 1)
    edges = np.unique(np.quantile(base, quantiles))
    if len(edges) < 2:
        return 0.0  # ベースラインが定数（分散ゼロ）→ 比較不能につき無変化扱い

    base_counts, _ = np.histogram(base, bins=edges)
    curr_counts, _ = np.histogram(curr, bins=edges)
    # 範囲外（直近データがベースライン範囲を超えた分）は端のビンに寄せる。
    base_pct = base_counts / len(base) + _EPS
    curr_pct = curr_counts / len(curr) + _EPS

    psi = float(np.sum((curr_pct - base_pct) * np.log(curr_pct / base_pct)))
    return round(psi, 6)


async def check_feature_drift(
    feature_name: str, *, baseline_start: str, baseline_end: str, current_start: str, current_end: str
) -> DriftResult | None:
    """1 特徴量について、指定期間のベースライン vs 直近の PSI を計算し永続化する."""
    baseline = await pl.list_feature_values(feature_name, since=baseline_start, until=baseline_end)
    current = await pl.list_feature_values(feature_name, since=current_start, until=current_end)

    psi = compute_psi(baseline, current)
    if psi is None:
        return None

    drift_flag = psi > settings.drift_psi_threshold
    await drift_db.insert_drift_snapshot(
        feature_name=feature_name,
        psi=psi,
        baseline_window=f"{baseline_start}~{baseline_end}",
        current_window=f"{current_start}~{current_end}",
        drift_flag=drift_flag,
    )
    return DriftResult(feature_name, psi, drift_flag, len(baseline), len(current))


async def run_drift_batch(
    *, baseline_start: str, baseline_end: str, current_start: str, current_end: str
) -> list[DriftResult]:
    """監視対象の全特徴量について PSI を計算・記録する（celery-beat が夜間に呼ぶ）."""
    results: list[DriftResult] = []
    for feature_name in MONITORED_FEATURES:
        result = await check_feature_drift(
            feature_name,
            baseline_start=baseline_start,
            baseline_end=baseline_end,
            current_start=current_start,
            current_end=current_end,
        )
        if result is not None:
            results.append(result)
    return results
