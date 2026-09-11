"""確度の事後較正（isotonic / Platt）— CL-7 / N3.

`plans/03_システム設計` §3.2。LLM が返す生の確度（`confidence_raw`, 0〜100）は較正されて
おらず「70% と言っている割に実測勝率は 50% 程度」のようなズレが起こりうる。決着済み
ピック（`pick_outcomes`）の (confidence_raw, win) ペアから較正器を学習し、以後のピックの
確度に適用してから `prediction_ledger.confidence` へ書く。

台帳が薄い（決着件数が少ない）うちは統計的に不安定なため **恒等写像へフォールバック**する:
- n >= `_MIN_ISOTONIC_SAMPLES`（40 件）: isotonic regression（`sklearn.isotonic`）
- n >= `_MIN_PLATT_SAMPLES`（10 件）: Platt scaling（1 変数ロジスティック回帰）
- それ未満: identity（`confidence = confidence_raw`）

較正器は `data/calibrators/<scope>_<horizon_days>.joblib` に永続化し、ピック生成時（同期・
軽量）に読み込んで適用する。学習（重い）は `eval_service` の夜間バッチ経由でのみ行う。
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Literal, Protocol

import joblib
import numpy as np
from sklearn.isotonic import IsotonicRegression
from sklearn.linear_model import LogisticRegression

logger = logging.getLogger(__name__)

CalibrationMethod = Literal["isotonic", "platt", "identity"]

_MIN_ISOTONIC_SAMPLES = 40
_MIN_PLATT_SAMPLES = 10

# リポジトリルート = backend/services/registry/calibration.py から 3 つ上。
_CALIBRATOR_DIR = Path(__file__).resolve().parents[3] / "data" / "calibrators"


class _Calibrator(Protocol):
    def predict(self, x: np.ndarray) -> np.ndarray: ...


def _path(scope: str, horizon_days: int) -> Path:
    return _CALIBRATOR_DIR / f"{scope}_{horizon_days}.joblib"


def fit_and_save(scope: str, horizon_days: int, confidence_raw: list[float], wins: list[bool]) -> CalibrationMethod:
    """決着済みピックの (confidence_raw, win) から較正器を学習し永続化する.

    サンプル不足時は永続化せず（既存ファイルがあれば削除して identity に戻す）
    ``"identity"`` を返す。返り値は実際に使われた較正方式。
    """
    n = len(confidence_raw)
    if n != len(wins):
        raise ValueError(f"confidence_raw と wins の長さが一致しません（{n} vs {len(wins)}）")

    path = _path(scope, horizon_days)
    x = np.asarray(confidence_raw, dtype=float) / 100.0
    y = np.asarray([1.0 if w else 0.0 for w in wins], dtype=float)

    if n >= _MIN_ISOTONIC_SAMPLES and len(set(y.tolist())) > 1:
        model: _Calibrator = IsotonicRegression(y_min=0.0, y_max=1.0, out_of_bounds="clip").fit(x, y)
        method: CalibrationMethod = "isotonic"
    elif n >= _MIN_PLATT_SAMPLES and len(set(y.tolist())) > 1:
        model = LogisticRegression().fit(x.reshape(-1, 1), y)
        method = "platt"
    else:
        path.unlink(missing_ok=True)
        logger.info("較正: scope=%s horizon=%d はサンプル %d 件で不足のため identity", scope, horizon_days, n)
        return "identity"

    _CALIBRATOR_DIR.mkdir(parents=True, exist_ok=True)
    joblib.dump({"method": method, "model": model}, path)
    logger.info("較正: scope=%s horizon=%d を %s で学習しました（n=%d）", scope, horizon_days, method, n)
    return method


def load_calibrator(scope: str, horizon_days: int) -> tuple[_Calibrator, CalibrationMethod] | None:
    """永続化済みの較正器を読み込む（無ければ None）."""
    path = _path(scope, horizon_days)
    if not path.is_file():
        return None
    try:
        payload = joblib.load(path)
        return payload["model"], payload["method"]
    except Exception:  # noqa: BLE001 — 破損ファイル等はフェイルソフトで identity 扱いにする
        logger.warning("較正器の読み込みに失敗しました: %s", path, exc_info=True)
        return None


def apply_calibration(scope: str, horizon_days: int, confidence_raw: float) -> tuple[float, CalibrationMethod]:
    """confidence_raw（0〜100）を較正して返す。較正器が無ければ恒等写像."""
    loaded = load_calibrator(scope, horizon_days)
    if loaded is None:
        return confidence_raw, "identity"

    model, method = loaded
    x = np.asarray([confidence_raw / 100.0])
    try:
        if method == "platt":
            proba = float(model.predict_proba(x.reshape(-1, 1))[0][1])  # type: ignore[attr-defined]
        else:
            proba = float(model.predict(x)[0])
    except Exception:  # noqa: BLE001 — 予測失敗時も本処理を止めない
        logger.warning("較正の適用に失敗しました（identity にフォールバック）: scope=%s", scope, exc_info=True)
        return confidence_raw, "identity"

    return round(max(0.0, min(100.0, proba * 100.0)), 1), method
