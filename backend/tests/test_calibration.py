"""確度の事後較正（isotonic / Platt）の検証（CL-7 / N3）."""

from __future__ import annotations

import random

from backend.services.registry import calibration

# 較正器の保存先は conftest の `_isolated_calibrator_dir`（autouse）が毎テスト隔離する。


def test_fit_and_save_falls_back_to_identity_with_few_samples() -> None:
    method = calibration.fit_and_save("mid_term", 20, [70.0, 80.0, 60.0], [True, True, False])
    assert method == "identity"
    assert calibration.load_calibrator("mid_term", 20) is None


def test_fit_and_save_uses_platt_with_moderate_samples() -> None:
    rng = random.Random(42)
    raw = [rng.uniform(30, 90) for _ in range(15)]
    wins = [r > 60 for r in raw]  # 確度が高いほど勝ちやすい傾向
    method = calibration.fit_and_save("short_term", 3, raw, wins)
    assert method == "platt"
    loaded = calibration.load_calibrator("short_term", 3)
    assert loaded is not None and loaded[1] == "platt"


def test_fit_and_save_uses_isotonic_with_many_samples_and_monotonic_output() -> None:
    rng = random.Random(1)
    raw = [rng.uniform(20, 95) for _ in range(60)]
    wins = [r > 55 + rng.uniform(-5, 5) for r in raw]
    method = calibration.fit_and_save("mid_term", 20, raw, wins)
    assert method == "isotonic"

    low, _ = calibration.apply_calibration("mid_term", 20, 30.0)
    high, _ = calibration.apply_calibration("mid_term", 20, 90.0)
    assert low <= high  # 単調性（isotonic の定義上、確度が高いほど較正後も高いか同値）


def test_apply_calibration_without_fitted_model_is_identity() -> None:
    conf, method = calibration.apply_calibration("mid_term", 20, 73.4)
    assert method == "identity"
    assert conf == 73.4


def test_fit_and_save_removes_existing_file_when_samples_drop_below_threshold() -> None:
    rng = random.Random(7)
    raw = [rng.uniform(20, 95) for _ in range(60)]
    wins = [r > 55 for r in raw]
    calibration.fit_and_save("mid_term", 5, raw, wins)
    assert calibration.load_calibrator("mid_term", 5) is not None

    calibration.fit_and_save("mid_term", 5, raw[:3], wins[:3])
    assert calibration.load_calibrator("mid_term", 5) is None
