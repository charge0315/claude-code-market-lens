"""断面プール型モデル（P5d）の学習コアとオーケストレータ.

Market Lens `backend/services/pool_training_service.py` から移植。変更点:
- `database.insert_model`/`activate_model`（Market Lens の per-ticker `is_active` フラグ方式）は
  Alpha Forge には存在しない。代わりに `services/registry/model_registry.ensure_registered` +
  `bootstrap_champion_if_missing` を使う（🔧）。初回バージョンは無条件で champion（lane="ml_pool"）
  になり、以降は `services/registry/promotion.evaluate_ml_pool_promotion` の人手承認ゲートを通す
  （`plans/03_システム設計` §3.3、N1 の champion/challenger を実 ML モデルへ適用したもの）。
  そのため `run_pool_training` は Market Lens と異なり **常に active にはしない**。
- モデルファイル保存先は `services/registry/calibration.py` の `_CALIBRATOR_DIR` と同じ規約で
  リポジトリ直下 `data/models/`。

`train_pool_model(panel)` から `panel_feature_service.build_panel` が返す「銘柄 × 営業日」の
長パネルを、「その営業日の universe 内で前方 H 日リターンが上位 `POOL_TOP_FRACTION` に入るか」を
予測する **1 個の** XGBoost 分類器として学習する（per-ticker ローテーションとは別系統。
Alpha Forge は per-ticker ローテーションを移植しない方針 — `plans/04_タスクリスト.md` P5d 参照）。
"""

from __future__ import annotations

import asyncio
import logging
import os
import uuid
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Final, cast

import joblib
import numpy as np
import pandas as pd
from xgboost import XGBClassifier

from backend.services.db import model_registry_db
from backend.services.jst_time import today_jst
from backend.services.learning.panel_feature_service import (
    add_ticker_target_encoding,
    build_panel,
    compute_ticker_te_map,
)
from backend.services.learning.pool_labeling import POOL_HORIZON_DAYS
from backend.services.learning.pool_model import POOL_LANE
from backend.services.ledger.eval_metrics import decile_return_spread, evaluate_classification
from backend.services.registry.model_registry import bootstrap_champion_if_missing, ensure_registered

logger = logging.getLogger(__name__)

# モデルファイルの保存先。`services/registry/calibration.py` の _CALIBRATOR_DIR と同じ規約
# （backend/services/learning/pool_training_service.py から見てリポジトリ直下 data/models）。
_MODEL_DIR: Final[Path] = Path(__file__).resolve().parents[3] / "data" / "models"
# 学習パネルの as_of 営業日数（既定 ~2 年）。widen するほど J-Quants 一括バー呼び出しが
# 増える（as_of ごとに t と t+H の2回）ため、まずは控えめに。
_DEFAULT_PANEL_BDAYS: Final[int] = 500
# t+H の J-Quants バーが確実に存在するよう、as_of 終端をさらに数営業日手前に置く。
_RESOLVE_BUFFER_BDAYS: Final[int] = 3

# パネルのうち特徴量ではない列（ラベル・識別子・生前方リターン）。
_NON_FEATURE_COLS: Final[frozenset[str]] = frozenset({"date", "code", "label", "fwd_return"})
# XGBoost に native カテゴリとして渡す列。
_CATEGORICAL_COLS: Final[tuple[str, ...]] = ("sector",)

# 学習に必要な最小ラベル付き行数（これ未満は学習しない）。
_MIN_LABELED_ROWS: Final[int] = 200
# 保存フォーマットのバージョン（将来の payload 変更検出用）。
_FORMAT_VERSION: Final[int] = 1

_DEFAULT_XGB_PARAMS: Final[dict[str, object]] = {
    "n_estimators": 300,
    "max_depth": 6,
    "learning_rate": 0.05,
    "subsample": 0.8,
    "colsample_bytree": 0.8,
    "tree_method": "hist",
    "enable_categorical": True,
    "eval_metric": "logloss",
}


def _feature_columns(panel: pd.DataFrame) -> list[str]:
    """パネルから特徴量列名を安定順で返す（識別子・ラベル・生前方リターンを除く）."""
    return [c for c in panel.columns if c not in _NON_FEATURE_COLS]


def _as_model_frame(panel: pd.DataFrame, feature_cols: list[str]) -> pd.DataFrame:
    """feature_cols だけを取り出し、カテゴリ列を category dtype にした DataFrame を返す."""
    frame = panel.reindex(columns=feature_cols).copy()
    for col in _CATEGORICAL_COLS:
        if col in frame.columns:
            frame[col] = frame[col].astype("category")
    return frame


def _purged_date_split(dates: pd.Series, *, val_fraction: float, gap_bdays: int) -> tuple[pd.Series, pd.Series]:
    """営業日ラベルの Series から (train_mask, val_mask) を返す（日付単位・境界パージ付き）.

    末尾 `val_fraction` 割合のユニーク日付を val、それ以外を train 候補とし、
    train のうち「最初の val 日から `gap_bdays` 営業日前」以降の日付を落とす
    （その日のラベルが val 期間の価格を参照するリークを断つ）。
    """
    unique_dates = sorted(pd.unique(dates))
    n = len(unique_dates)
    n_val = max(1, int(round(n * val_fraction)))
    val_dates = set(unique_dates[n - n_val :])
    first_val = pd.Timestamp(min(val_dates))
    purge_before = (first_val - pd.tseries.offsets.BDay(gap_bdays)).strftime("%Y-%m-%d")

    val_mask = dates.isin(val_dates)
    train_mask = (~val_mask) & (dates < purge_before)
    return train_mask, val_mask


class PoolClassifier:
    """断面プール分類器の軽量ラッパ（fit / predict_proba / save / load）."""

    objective: Final[str] = "classification"

    def __init__(
        self,
        model: XGBClassifier | None = None,
        feature_cols: list[str] | None = None,
        ticker_te_map: dict[str, float] | None = None,
    ) -> None:
        self.model = model
        self.feature_cols: list[str] = feature_cols or []
        # 学習データの per-ticker 平滑化ラベル平均 {code: te} ＋ {"__global__": mean}。
        # 推論時に銘柄の ticker_te を引くために使う（build_inference_row）。
        self.ticker_te_map: dict[str, float] = ticker_te_map or {}

    def fit(self, X: pd.DataFrame, y: pd.Series, *, scale_pos_weight: float, seed: int = 42) -> None:
        self.feature_cols = list(X.columns)
        params = {**_DEFAULT_XGB_PARAMS, "scale_pos_weight": scale_pos_weight, "random_state": seed}
        self.model = XGBClassifier(**params)
        self.model.fit(_as_model_frame(X, self.feature_cols), y)

    def predict_proba(self, X: pd.DataFrame) -> np.ndarray:
        """陽性クラス（label=1=上位）の確率を長さ n の1次元配列で返す."""
        if self.model is None:
            raise ValueError("モデルが未学習です")
        frame = _as_model_frame(X, self.feature_cols)
        proba = np.asarray(self.model.predict_proba(frame))
        return proba[:, 1]

    def save(self, path: str) -> str:
        if self.model is None:
            raise ValueError("学習済みモデルが存在しません")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        joblib.dump(
            {
                "format_version": _FORMAT_VERSION,
                "model": self.model,
                "feature_cols": self.feature_cols,
                "objective": self.objective,
                "ticker_te_map": self.ticker_te_map,
            },
            path,
        )
        return path

    @classmethod
    def load(cls, path: str) -> PoolClassifier:
        if not os.path.exists(path):
            raise FileNotFoundError(f"モデルファイルが見つかりません: {path}")
        payload = joblib.load(path)
        return cls(
            model=payload["model"],
            feature_cols=list(payload.get("feature_cols", [])),
            ticker_te_map=dict(payload.get("ticker_te_map", {})),
        )


def train_pool_model(
    panel: pd.DataFrame, *, val_fraction: float = 0.2, seed: int = 42
) -> tuple[PoolClassifier, dict[str, float | str | int]]:
    """断面パネルからプール分類器を学習し、held-out val の評価指標とともに返す.

    - ラベル欠損行は除外。日付単位の purged walk-forward（gap = `POOL_HORIZON_DAYS`）。
    - ticker ターゲットエンコーディングは train 行のみで作る。
    - 不均衡補正 `scale_pos_weight = neg/pos`（train 基準）。
    - 評価: AUC / Brier / brier_skill / pos_rate ＋ 予測確率十分位の実現リターンスプレッド。
    """
    labeled = panel[panel["label"].notna()].copy()
    if len(labeled) < _MIN_LABELED_ROWS:
        raise ValueError(f"ラベル付き行が少なすぎます（{len(labeled)} < {_MIN_LABELED_ROWS}）")

    train_mask, val_mask = _purged_date_split(labeled["date"], val_fraction=val_fraction, gap_bdays=POOL_HORIZON_DAYS)
    if not train_mask.any() or not val_mask.any():
        raise ValueError("purged 分割の結果 train または val が空になりました")

    encoded = add_ticker_target_encoding(labeled, train_mask=train_mask)
    feature_cols = _feature_columns(encoded)

    X = encoded.reindex(columns=feature_cols)
    y = encoded["label"].astype(int)
    X_train, y_train = X[train_mask.to_numpy()], y[train_mask.to_numpy()]
    X_val, y_val = X[val_mask.to_numpy()], y[val_mask.to_numpy()]

    pos = int(y_train.sum())
    neg = int(len(y_train) - pos)
    scale_pos_weight = neg / pos if pos > 0 else 1.0

    clf = PoolClassifier(ticker_te_map=compute_ticker_te_map(encoded, train_mask=train_mask))
    clf.fit(X_train, y_train, scale_pos_weight=scale_pos_weight, seed=seed)
    p_val = clf.predict_proba(X_val)

    est = evaluate_classification(y_val.to_numpy().tolist(), p_val.tolist())
    val_dates = sorted(pd.unique(encoded.loc[val_mask, "date"]))
    metrics: dict[str, float | str | int] = {
        "objective": "classification",
        "n_train": int(len(y_train)),
        "n_val": int(len(y_val)),
        "val_start": str(val_dates[0]),
        "val_end": str(val_dates[-1]),
        "pos_rate": est.pos_rate if est else 0.0,
        "auc": (est.auc if est and est.auc is not None else 0.5),
        "brier": est.brier if est else 0.0,
        "brier_skill": est.brier_skill if est else 0.0,
    }

    fwd = encoded.loc[val_mask, "fwd_return"] if "fwd_return" in encoded.columns else None
    if fwd is not None and fwd.notna().any():
        valid = fwd.notna().to_numpy()
        ds = decile_return_spread(p_val[valid].tolist(), fwd.to_numpy()[valid].tolist(), n_deciles=10)
        if ds is not None:
            metrics["decile_spread"] = ds.spread
            metrics["decile_top_mean"] = ds.top_mean
            metrics["decile_bottom_mean"] = ds.bottom_mean

    logger.info(
        "プールモデル学習: n_train=%d n_val=%d AUC=%.3f brier_skill=%.3f",
        metrics["n_train"],
        metrics["n_val"],
        metrics["auc"],
        metrics["brier_skill"],
    )
    return clf, metrics


# ---------------------------------------------------------------------------
# オーケストレータ（I/O・DB あり）
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PoolTrainingSummary:
    """`run_pool_training` の実行結果（Celery タスクの戻り値用）."""

    status: str  # "trained" / "skipped"（データ不足・J-Quants 未設定）
    n_panel_rows: int
    metrics: dict[str, float | str | int] = field(default_factory=dict)
    version: str | None = None
    is_champion: bool = False
    detail: str | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "status": self.status,
            "n_panel_rows": self.n_panel_rows,
            "metrics": self.metrics,
            "version": self.version,
            "is_champion": self.is_champion,
            "detail": self.detail,
        }


def default_as_of_dates(panel_bdays: int = _DEFAULT_PANEL_BDAYS) -> list[str]:
    """前方リターンが解決済みの範囲で、直近 `panel_bdays` 営業日の as_of 日付列を返す.

    終端 = 今日（JST）から `POOL_HORIZON_DAYS + _RESOLVE_BUFFER_BDAYS` 営業日前
    （t+H のバーが必ず存在する保証を持たせる）。
    """
    end = pd.Timestamp(today_jst()) - pd.tseries.offsets.BDay(POOL_HORIZON_DAYS + _RESOLVE_BUFFER_BDAYS)
    start = end - pd.tseries.offsets.BDay(panel_bdays - 1)
    return [d.strftime("%Y-%m-%d") for d in pd.bdate_range(start, end)]


async def run_pool_training(*, as_of_dates: Sequence[str] | None = None, seed: int = 42) -> PoolTrainingSummary:
    """断面プールモデルを1本学習し `model_registry` へ登録する.

    `as_of_dates` 省略時は `default_as_of_dates()`。重い `build_panel`（ユニバース走査＋
    J-Quants 一括バー）と学習・保存は `asyncio.to_thread` へ逃がす。J-Quants 未設定・
    データ不足（ラベル付き行が `_MIN_LABELED_ROWS` 未満等）は例外にせず `status="skipped"`
    で正常終了する（他の自走タスクに影響させない）。

    lane="ml_pool" に champion が居なければこのバージョンが無条件で champion になる（N1、
    初回ブートストラップ）。既に champion が居る場合は登録のみ行い（`is_champion=False`）、
    `services/registry/promotion.evaluate_ml_pool_promotion` の人手承認ゲートを経てから
    昇格する（🔧 Market Lens は 1 本しか無い前提で即 `activate_model` していたが、Alpha Forge
    は再学習後の自動切替をしない）。
    """
    dates = list(as_of_dates) if as_of_dates is not None else default_as_of_dates()

    panel = await build_panel(dates)
    if panel.empty or "label" not in panel.columns or panel["label"].notna().sum() < _MIN_LABELED_ROWS:
        n_labeled = 0 if panel.empty or "label" not in panel.columns else int(panel["label"].notna().sum())
        logger.warning("プールモデル学習をスキップ: ラベル付き行 %d 件（J-Quants 未設定/データ不足）", n_labeled)
        return PoolTrainingSummary(status="skipped", n_panel_rows=int(len(panel)), detail=f"labeled_rows={n_labeled}")

    try:
        clf, metrics = await asyncio.to_thread(train_pool_model, panel, seed=seed)
    except ValueError as exc:
        logger.warning("プールモデル学習をスキップ: %s", exc)
        return PoolTrainingSummary(status="skipped", n_panel_rows=int(len(panel)), detail=str(exc))

    version = f"pool-{uuid.uuid4()}"
    artifact_path = str(_MODEL_DIR / f"{version}.joblib")
    await asyncio.to_thread(clf.save, artifact_path)

    # 🆕 P29: PIT 特徴量の被覆率ゲート判定結果（`panel_feature_service._attach_pit_features`
    # が `panel.attrs["pit_coverage"]` へ記録済み）を、このモデルバージョンの val_metrics へ
    # 転記する。`PIT_FEATURES_ENABLED=false`（既定）では属性自体が付かないため何もしない。
    val_metrics = cast("dict[str, object]", dict(metrics))
    pit_coverage = panel.attrs.get("pit_coverage")
    if pit_coverage is not None:
        val_metrics["pit_coverage"] = pit_coverage

    await ensure_registered(
        version,
        lane=POOL_LANE,
        val_metrics=val_metrics,
        feature_list=clf.feature_cols,
        artifact_path=artifact_path,
    )
    is_champion = await bootstrap_champion_if_missing(POOL_LANE, version)

    logger.info("プールモデル学習完了: version=%s AUC=%.3f is_champion=%s", version, metrics["auc"], is_champion)
    return PoolTrainingSummary(
        status="trained", n_panel_rows=int(len(panel)), metrics=metrics, version=version, is_champion=is_champion
    )


async def load_pool_classifier(version: str) -> PoolClassifier:
    """指定バージョンの `PoolClassifier` を `model_registry.artifact_path` からロードする."""
    row = await model_registry_db.get_model(version)
    if row is None:
        raise ValueError(f"model_registry に未登録のバージョンです: {version}")
    artifact_path = str(row["artifact_path"])
    return await asyncio.to_thread(PoolClassifier.load, artifact_path)


__all__ = [
    "PoolClassifier",
    "PoolTrainingSummary",
    "default_as_of_dates",
    "load_pool_classifier",
    "run_pool_training",
    "train_pool_model",
]
