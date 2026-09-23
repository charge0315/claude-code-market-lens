"""ファクター実測 IC から合成スコアの重みを算出するサービス（shadow モード）.

Market Lens `backend/services/factor_weight_service.py` から移植。変更点（🔧）:
Market Lens は `signal_scan_ic_db`/`signal_scan_ic_service`（テーマ株スキャン専用の別バッチ・
別テーブル `signal_scan_ic_runs`）が蓄積した factor-IC を参照するが、Alpha Forge はその
スキャン基盤を移植していない（`plans/04_タスクリスト.md` の `signal_scan_*` は対象外のまま）。
代わりに、実際に本番ピックで使われている `recommender.FACTOR_WEIGHTS`
（technical/ml_prediction/fundamental/sentiment）を対象に、`prediction_ledger.
source_contributions`（各ピック時点のファクター別スコア）と `pick_outcomes.excess_return`
（決着後の実測超過リターン）を直接 `pick_outcome_db.list_resolved_for_eval` から結合し、
別バッチ・別テーブルなしで IC を算出する。

算出した重みはここでは一切使わない（shadow）。`GET /api/eval/factor-weights` で参照できる
だけで、`recommender.compute_recommendation` の合成には反映しない。shadow → 本番への切替は、
数週間の並走観測で実測重みが既定重みを上回ることを確認してから別途判断する
（このモジュールでは判断しない）。
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from typing import Final

from backend.services.db import pick_outcome_db
from backend.services.ledger.eval_metrics import spearman_ic
from backend.services.scoring.recommender import FACTOR_WEIGHTS

# IC 算出に使う既定ホライズン（保有期間の目安に近い長い方）。
DEFAULT_HORIZON_DAYS: Final[int] = 20

# 統計的信頼性の下限（このサンプル数未満のファクターは既定重みへフォールバック）。
_MIN_SAMPLES_FOR_IC: Final[int] = 20

# |IC| 比例の重みが1ファクターへ極端に偏らないよう、最小候補値の何倍までを上限にクリップする。
# Market Lens は 3.0（既定重みの spread が技術0.40:ファンダ0.30 で 1.33 倍と近接していた）を
# 使っていたが、Alpha Forge の既定重み（technical 0.35 : sentiment 0.10 = 3.5 倍）はこれより
# spread が広く、3.0 のままだと「IC 実測が一件も無い」フォールバックのみの状態でさえ
# 既定重みの比率が歪んでしまう（🔧）。既定重みの最大 spread（3.5 倍）を上回る値にして、
# フォールバックのみの状態では既定重みの比率をそのまま再現しつつ、実測 IC が極端な場合の
# クリップとしても機能する値にする。
_MAX_WEIGHT_RATIO: Final[float] = 5.0
_MIN_RAW_WEIGHT: Final[float] = 1e-4


def _f(value: object) -> float:
    return float(value) if isinstance(value, (int, float)) else 0.0


def _factor_score(source_contributions: Mapping[str, object], factor: str) -> float | None:
    entry = source_contributions.get(factor)
    if not isinstance(entry, Mapping):
        return None
    score = entry.get("score")
    return float(score) if isinstance(score, (int, float)) else None


async def compute_ic_weights(horizon_days: int = DEFAULT_HORIZON_DAYS) -> dict[str, float]:
    """直近の決着済みピックからファクター別 |IC| 比例の重みを算出する（shadow 用、未適用）.

    信頼できる IC 実測（サンプル数 >= `_MIN_SAMPLES_FOR_IC`）が無いファクターは
    `recommender.FACTOR_WEIGHTS` の既定重みにフォールバックする。戻り値は合計 1.0 に
    正規化済みで、`signal_scan_scoring.compute_composite` の `weights` 引数へそのまま渡せる形。
    """
    rows = await pick_outcome_db.list_resolved_for_eval(horizon_days=horizon_days)
    return ic_weights_from_rows(rows)


def ic_weights_from_rows(
    rows: Sequence[Mapping[str, object]], *, factors: Sequence[str] | None = None
) -> dict[str, float]:
    """決着済み行（`source_contributions` と `excess_return` を持つ）から |IC| 比例の重みを出す.

    🆕 P37: 過去日リプレイ（`services/replay/learning.py`）が専用台帳の行から同じ規則で重みを
    算出できるよう、DB 取得から切り離した。`source_contributions` は JSON 文字列（本番台帳）と
    解析済み dict（リプレイ台帳）の両方を受け付ける。`factors` を渡すとその集合だけで重みを作る
    （リプレイでは過去時点の値が無いファクターに既定重みが残ると誤解を招くため、呼び出し側で外す）。
    """
    raw: dict[str, float] = {}
    for factor in factors if factors is not None else tuple(FACTOR_WEIGHTS):
        pairs = [
            (score, _f(r["excess_return"]))
            for r in rows
            if (score := _factor_score(_source_contributions_of(r), factor)) is not None
        ]
        abs_ic = _mean_reliable_abs_ic(pairs)
        raw[factor] = abs_ic if abs_ic is not None else FACTOR_WEIGHTS[factor]

    return _normalize_with_ratio_clip(raw)


def _source_contributions_of(row: Mapping[str, object]) -> Mapping[str, object]:
    raw = row.get("source_contributions")
    if isinstance(raw, Mapping):
        return raw
    if not isinstance(raw, str) or not raw:
        return {}
    parsed = json.loads(raw)
    return parsed if isinstance(parsed, dict) else {}


def _mean_reliable_abs_ic(pairs: Sequence[tuple[float, float]]) -> float | None:
    """(factor_score, excess_return) の対から |IC| を算出する（サンプル不足は None）."""
    if len(pairs) < _MIN_SAMPLES_FOR_IC:
        return None
    scores = [p[0] for p in pairs]
    returns = [p[1] for p in pairs]
    ic = spearman_ic(scores, returns)
    return abs(ic) if ic is not None else None


def _normalize_with_ratio_clip(raw: Mapping[str, float]) -> dict[str, float]:
    """生の重み候補を下限フロア→比率クリップ→合計1.0正規化する."""
    if not raw:
        return {}
    floored = {k: max(v, _MIN_RAW_WEIGHT) for k, v in raw.items()}
    weight_cap = min(floored.values()) * _MAX_WEIGHT_RATIO
    clipped = {k: min(v, weight_cap) for k, v in floored.items()}
    total = sum(clipped.values())
    return {k: round(v / total, 4) for k, v in clipped.items()}
