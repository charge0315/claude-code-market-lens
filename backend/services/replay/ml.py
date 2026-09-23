"""過去日リプレイの断面プールモデル（🆕 P37）.

本番の断面プールモデル（`services/learning/pool_training_service.py`、lane="ml_pool"）と同じ
学習コア（`train_pool_model`）・断面特徴量（`add_cross_sectional_features`）・ラベル規則
（`cross_sectional_label`）を使い、リプレイ日 D の時点で確定していたデータだけで学習・推論する。

本番の `build_panel` は銘柄ごとに yfinance を叩いて毎回特徴量を作り直すが、リプレイでは
950 日 × 4000 銘柄で数十時間かかるため、**銘柄ごとに全期間の特徴量を 1 回だけ計算し日付で
切り出す**（`FeatureCache`）。これが未来リークにならないのは `build_feature_matrix` が過去方向
のみの計算だからで、その前提は `tests/test_replay_ml.py::test_feature_matrix_is_causal` で固定する。
切り出しは必ず `AsOfView.assert_visible` を通すので、D より後の行は取り出せない。

本番との差分:
- セクター列を持たない（当時の業種分類が残っておらず、現在の銘柄マスタを当てると上場廃止銘柄が
  欠けるため）。`add_cross_sectional_features` はセクター列が無ければセクター相対特徴量を作らない。
- PIT ファンダメンタル・センチメント特徴量は使わない（過去分が存在しない）。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Final

import numpy as np
import pandas as pd

from backend.services.data.jquants_client import JQuantsClient
from backend.services.learning.feature_engineering import build_feature_matrix
from backend.services.learning.panel_feature_service import PanelContext, add_cross_sectional_features
from backend.services.learning.pool_labeling import POOL_HORIZON_DAYS, cross_sectional_label
from backend.services.learning.pool_training_service import PoolClassifier, train_pool_model
from backend.services.replay.price_store import AsOfView, FutureDataAccessError, PriceStore
from backend.services.scoring.ml_score_provider import make_pool_ml_score_provider
from backend.services.scoring.recommender import MlScoreProvider

logger = logging.getLogger(__name__)

# 本番 `panel_feature_service._MIN_HISTORY_ROWS` と同じ（短すぎる系列は特徴量が安定しない）。
_MIN_HISTORY_ROWS: Final[int] = 80


@dataclass(frozen=True)
class ReplayMlConfig:
    """リプレイ内の再学習設定.

    既定値は本番のプールモデル（学習窓 500 営業日・ホライズン `POOL_HORIZON_DAYS`・解決バッファ 3）
    に合わせ、学習日は `stride_bdays` おきに間引く（隣接日の断面はほぼ同じ情報で、全日使うと
    学習時間だけが 5 倍になるため）。
    """

    horizon: int = POOL_HORIZON_DAYS
    window_bdays: int = 500
    stride_bdays: int = 5
    resolve_buffer_bdays: int = 3


class FeatureCache:
    """銘柄ごとに全期間で 1 回だけ計算した特徴量を、日付単位で切り出して返す."""

    def __init__(self, frame: pd.DataFrame) -> None:
        self._frame = frame.sort_values("date", kind="stable").reset_index(drop=True)
        dates = self._frame["date"].to_numpy()
        self._slices: dict[str, tuple[int, int]] = {}
        if len(dates):
            boundaries = np.flatnonzero(dates[1:] != dates[:-1]) + 1
            starts = np.concatenate(([0], boundaries))
            ends = np.concatenate((boundaries, [len(dates)]))
            self._slices = {str(dates[s]): (int(s), int(e)) for s, e in zip(starts, ends, strict=True)}

    @classmethod
    def build(cls, store: PriceStore) -> FeatureCache:
        """全銘柄の特徴量を計算する（1 銘柄あたり十数 ms。全期間を 1 回だけ）.

        全期間の履歴を読むため最終取引日のビューを使う。ここで作ったフレームは
        `rows_for_date` の `assert_visible` を通してしか外に出ない。
        """
        dates = store.trading_dates
        if not dates:
            return cls(pd.DataFrame(columns=["date", "code"]))
        full_view = store.view(dates[-1])
        frames: list[pd.DataFrame] = []
        for code in store.codes():
            df = full_view.history(code)
            if len(df) < _MIN_HISTORY_ROWS:
                continue
            try:
                feats, _ = build_feature_matrix(df, predict_mode=True)
            except (ValueError, RuntimeError):
                continue
            if feats.empty:
                continue
            sub = feats.astype(np.float32)
            aligned = df.loc[feats.index]
            sub["dollar_volume"] = (aligned["Close"] * aligned["Volume"]).astype(np.float32).to_numpy()
            sub["date"] = [ts.strftime("%Y-%m-%d") for ts in feats.index]
            sub["code"] = code
            frames.append(sub.reset_index(drop=True))
        frame = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(columns=["date", "code"])
        logger.info("リプレイ特徴量キャッシュ: %d 銘柄 / %d 行", len(frames), len(frame))
        return cls(frame)

    def rows_for_date(self, view: AsOfView, date: str) -> pd.DataFrame:
        """`date`（<= view.as_of）の全銘柄の特徴量行（コピー）."""
        view.assert_visible(date)
        span = self._slices.get(date)
        if span is None:
            return self._frame.iloc[0:0].copy()
        return self._frame.iloc[span[0] : span[1]].copy()


def training_dates(view: AsOfView, cfg: ReplayMlConfig) -> list[str]:
    """リプレイ日の時点でラベル（t + horizon 営業日の終値）が確定している学習日を返す.

    最新の学習日は「as_of から horizon + 解決バッファ営業日前」。そこから `window_bdays` 遡った
    範囲を、最新日を起点に `stride_bdays` おきに間引く。
    """
    dates = view.trading_dates_until_as_of()
    last = len(dates) - 1 - (cfg.horizon + cfg.resolve_buffer_bdays)
    if last < 0:
        return []
    first = max(0, last - cfg.window_bdays + 1)
    return list(reversed(dates[first : last + 1][::-1][:: cfg.stride_bdays]))


def forward_returns(view: AsOfView, date: str, *, horizon: int) -> dict[str, float]:
    """`date` から `horizon` 営業日後までの終値リターン（キー = J-Quants 5 桁コード）.

    終点日が as_of より後なら `FutureDataAccessError`（`closes_on` の門番）。
    """
    view.assert_visible(date)
    dates = view.trading_dates_until_as_of()
    if date not in dates:
        return {}
    end_idx = dates.index(date) + horizon
    if end_idx >= len(dates):
        raise FutureDataAccessError(f"{view.as_of} 時点で {date} の {horizon} 営業日後リターンは確定していません")
    start = view.closes_on(date)
    end = view.closes_on(dates[end_idx])
    joined = pd.concat([start.rename("s"), end.rename("e")], axis=1, join="inner")
    joined = joined[(joined["s"] > 0.0) & joined["e"].notna()]
    return {str(code): float(e / s - 1.0) for code, s, e in zip(joined.index, joined["s"], joined["e"], strict=True)}


def build_training_panel(view: AsOfView, cache: FeatureCache, cfg: ReplayMlConfig) -> pd.DataFrame:
    """学習日ごとの特徴量行に断面ランクラベルと前方リターンを付け、断面特徴量を足した長パネル."""
    frames: list[pd.DataFrame] = []
    for date in training_dates(view, cfg):
        rows = cache.rows_for_date(view, date)
        if rows.empty:
            continue
        fwd = forward_returns(view, date, horizon=cfg.horizon)
        labels = cross_sectional_label(fwd)
        if not labels:
            continue
        code5 = rows["code"].map(JQuantsClient._to_5digit)
        rows["label"] = code5.map(labels)
        rows["fwd_return"] = code5.map(fwd)
        frames.append(rows)
    if not frames:
        return pd.DataFrame()
    return add_cross_sectional_features(pd.concat(frames, ignore_index=True))


def train_at(
    view: AsOfView, cache: FeatureCache, cfg: ReplayMlConfig, *, seed: int = 42
) -> tuple[PoolClassifier, dict[str, float | str | int]] | None:
    """リプレイ日の時点のデータだけでプール分類器を学習する（データ不足なら None）."""
    panel = build_training_panel(view, cache, cfg)
    if panel.empty:
        return None
    try:
        return train_pool_model(panel, seed=seed)
    except ValueError as exc:
        logger.info("リプレイ %s: プールモデル学習をスキップ（%s）", view.as_of, exc)
        return None


def score_provider_at(view: AsOfView, cache: FeatureCache, clf: PoolClassifier | None) -> MlScoreProvider:
    """リプレイ日の断面から ML スコア provider を作る（本番 `make_pool_ml_score_provider` と同じ変換）."""
    rows = cache.rows_for_date(view, view.as_of)
    if rows.empty:
        ctx = PanelContext(as_of=view.as_of, frame=pd.DataFrame().set_index(pd.Index([], name="code")))
    else:
        ctx = PanelContext(as_of=view.as_of, frame=add_cross_sectional_features(rows).set_index("code"))
    return make_pool_ml_score_provider(ctx, clf)
