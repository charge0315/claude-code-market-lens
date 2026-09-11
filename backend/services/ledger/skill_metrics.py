"""予測モデルの「ナイーブ予測に対する改善度」を表す skill score の共通実装.

Market Lens `backend/services/skill_metrics.py` から移植（変更なし）。RMSE 単体では
「変化率 0」と予測し続けるナイーブモデルより良いか分からないため、その判定基準を集約する。
"""

from __future__ import annotations

import numpy as np


def naive_rmse(y_true: np.ndarray) -> float:
    """「変化率 0（明日も今日と同じ）」と予測し続けた場合の RMSE（評価の最低ライン）."""
    y_true_arr = np.asarray(y_true, dtype=float)
    return float(np.sqrt(np.mean(y_true_arr**2)))


def skill_score(rmse: float, naive_rmse_value: float) -> float:
    """ナイーブ予測に対する改善度。1 に近いほど良く、0 以下はナイーブ予測以下."""
    if naive_rmse_value <= 0.0:
        return 0.0
    return float(1.0 - (rmse / naive_rmse_value) ** 2)
