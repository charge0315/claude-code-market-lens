"""断面プール型モデル（P5d）のラベリング・プリミティブ.

Market Lens `backend/services/pool_labeling.py` から移植（変更なし）。`panel_feature_service`
（学習用パネル生成）が使う。

プールモデルのターゲットは「ある営業日 t の前方 H 営業日リターンが、その日の universe 全体の
中で上位 `POOL_TOP_FRACTION` に入るか」の2値分類。per-ticker の絶対水準（SL/TP、生リターン）は
断面ランクで相対化されるため持ち込まない。
"""

from __future__ import annotations

import math
from collections.abc import Mapping

from scipy.stats import rankdata

# 前方リターンの評価ホライズン（営業日）。
POOL_HORIZON_DAYS = 10
# 「買うべき上位」とみなす当日 universe 内の割合（上位20%を label=1）。
POOL_TOP_FRACTION = 0.2
# 断面ランクを意味のある統計にするために必要な、その日の有効銘柄数の下限。
_MIN_UNIVERSE_FOR_LABELS = 20


def cross_sectional_label(forward_returns_by_code: Mapping[str, float | None]) -> dict[str, float]:
    """ある営業日の {銘柄コード: 前方 H 日リターン} から断面ランクラベル {コード: 0.0/1.0} を返す.

    - 前方リターンが None / 非有限（上場前・上場廃止・H 日後バー欠損）の銘柄は
      出力から除外する（＝学習・評価サンプルに含めない）。
    - 有効銘柄が `_MIN_UNIVERSE_FOR_LABELS` 未満なら空 dict を返す（その日は使わない）。
    - パーセンタイル `q = (rank - 1) / (n - 1)`（rank は同順位平均）。
      `q >= 1 - POOL_TOP_FRACTION` の銘柄が label=1。
    """
    finite: dict[str, float] = {
        code: float(ret)
        for code, ret in forward_returns_by_code.items()
        if ret is not None and math.isfinite(float(ret))
    }
    if len(finite) < _MIN_UNIVERSE_FOR_LABELS:
        return {}

    codes = list(finite)
    ranks = rankdata([finite[code] for code in codes], method="average")
    denom = len(codes) - 1
    threshold = 1.0 - POOL_TOP_FRACTION
    return {code: (1.0 if (rank - 1.0) / denom >= threshold else 0.0) for code, rank in zip(codes, ranks, strict=True)}
