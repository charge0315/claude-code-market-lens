"""purged train/val 分割の検証（Market Lens から移植）."""

from __future__ import annotations

import numpy as np
import pytest

from backend.services.learning.ts_validation import purged_train_val_split


def test_split_preserves_time_order_and_gap() -> None:
    x = np.arange(100).reshape(100, 1)
    y = np.arange(100)
    xt, yt, xv, yv = purged_train_val_split(x, y, val_ratio=0.2, gap=5)
    # val は末尾 20、train は先頭 75（gap 5 を破棄）。
    assert len(xv) == 20 and len(xt) == 75
    assert int(yv[0]) == 80
    assert int(yt[-1]) == 74  # gap で 75..79 が捨てられている


def test_rejects_mismatched_lengths() -> None:
    with pytest.raises(ValueError, match="長さが一致"):
        purged_train_val_split(np.zeros((10, 1)), np.zeros(9))


@pytest.mark.parametrize("ratio", [0.0, 1.0, -0.1])
def test_rejects_bad_val_ratio(ratio: float) -> None:
    with pytest.raises(ValueError, match="val_ratio"):
        purged_train_val_split(np.zeros((10, 1)), np.zeros(10), val_ratio=ratio)


def test_rejects_gap_that_empties_train() -> None:
    with pytest.raises(ValueError, match="train が空"):
        purged_train_val_split(np.zeros((10, 1)), np.zeros(10), val_ratio=0.5, gap=6)
