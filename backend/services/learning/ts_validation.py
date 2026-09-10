"""時系列データ向けの train/val 分割ユーティリティ.

Market Lens `backend/services/ts_validation.py` から移植（変更なし）。
株価シーケンスをランダムシャッフルで分割すると horizon リークが起きるため、時間順を
維持したまま境界に gap を設けて分割する（purged split）。継続学習のウォークフォワード
検証（P5、時系列 CV のみ）で使う。
"""

from __future__ import annotations

import numpy as np


def purged_train_val_split(
    X: np.ndarray,
    y: np.ndarray,
    val_ratio: float = 0.15,
    gap: int = 0,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """時系列順を保ったまま train/val に分割し、境界に gap を設けてリークを防ぐ.

    Args:
        X: 先頭軸がサンプル数の入力配列（2 次元でも (n_samples, seq_len, n_features) の 3 次元でも可）
        y: shape (n_samples,) のラベル配列
        val_ratio: 検証データとして末尾から確保する比率（0 と 1 の間）
        gap: train 末尾と val 先頭の間で破棄するサンプル数（通常 `seq_len + forecast_horizon`）

    Returns:
        (X_train, y_train, X_val, y_val)。いずれも numpy スライス（view）。

    Raises:
        ValueError: 入力長不一致、val_ratio / gap が不正、または gap が大きすぎて train が空になる場合
    """
    if len(X) != len(y):
        raise ValueError(f"X と y の長さが一致しません（X={len(X)}, y={len(y)}）")

    if not (0.0 < val_ratio < 1.0):
        raise ValueError(f"val_ratio は 0 と 1 の間である必要があります（val_ratio={val_ratio}）")

    if gap < 0:
        raise ValueError(f"gap は 0 以上である必要があります（gap={gap}）")

    n = len(X)
    val_size = max(1, int(n * val_ratio))
    train_size = n - val_size - gap

    if train_size < 1:
        required = val_size + gap + 1
        raise ValueError(
            f"gap が大きすぎて train が空になります（n={n}, val_size={val_size}, gap={gap}）。"
            f"最低でも {required} 件のサンプルが必要です"
        )

    X_train = X[:train_size]
    y_train = y[:train_size]
    X_val = X[n - val_size :]
    y_val = y[n - val_size :]

    return X_train, y_train, X_val, y_val
