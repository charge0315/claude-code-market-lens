"""過去日リプレイの答え合わせ結果からの学習・集計（🆕 P37）.

リプレイ台帳（`replay_picks` + `replay_outcomes`）から次を作る。**いずれも本番へ自動反映しない**
（CLAUDE.md「config・コードの自動適用はしない」「昇格は提案のみ」）:

- ホライズン別の成績（勝率・平均超過リターン・利確/損切到達率）。
- 合成スコア帯ごとの実測勝率（UI の較正曲線表示用）と、合成スコア → 勝率の較正器。
  較正器は本番の LLM 確度用（scope = horizon_type）と衝突しない専用 scope
  （`replay_composite_<horizon_type>`）で保存し、本番のピック生成には適用しない。
- ファクター別 IC と、本番 `factor_weight_service` と同じ規則の |IC| 比例重み（shadow 表示用）。
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from statistics import mean
from typing import Final

from backend.services.db import replay_db
from backend.services.ledger.eval_metrics import spearman_ic
from backend.services.ledger.outcome_resolver import HORIZON_SETS
from backend.services.registry.calibration import fit_and_save
from backend.services.registry.factor_weight_service import ic_weights_from_rows
from backend.services.scoring.recommender import FACTOR_WEIGHTS

# IC 重み・較正器を学習するホライズン（本番の E3 ゲートと同じ: 短期 3 / 中長期 20 営業日）。
GATE_HORIZONS: Final[dict[str, int]] = {"short_term": 3, "mid_term": 20}
_BUCKET_WIDTH: Final[float] = 5.0
_MIN_SAMPLES_FOR_IC: Final[int] = 20


def _f(value: object) -> float | None:
    if isinstance(value, bool):
        return None
    return float(value) if isinstance(value, (int, float)) else None


def performance_stats(rows: Sequence[Mapping[str, object]]) -> dict[str, float | int]:
    if not rows:
        return {"n": 0}
    realized = [_f(r.get("realized_return")) or 0.0 for r in rows]
    excess = [_f(r.get("excess_return")) or 0.0 for r in rows]
    return {
        "n": len(rows),
        "win_rate": round(sum(1 for r in rows if r.get("win")) / len(rows), 4),
        "avg_realized": round(mean(realized), 6),
        "avg_excess": round(mean(excess), 6),
        "hit_target_rate": round(sum(1 for r in rows if r.get("hit_target")) / len(rows), 4),
        "hit_stop_rate": round(sum(1 for r in rows if r.get("hit_stop")) / len(rows), 4),
    }


def composite_calibration_table(rows: Sequence[Mapping[str, object]]) -> list[dict[str, float | int]]:
    """合成スコアを 5 点刻みの帯に分け、帯ごとの件数と実測勝率を返す（件数のある帯のみ、昇順）."""
    buckets: dict[float, list[bool]] = {}
    for r in rows:
        score = _f(r.get("composite_score"))
        if score is None:
            continue
        low = (score // _BUCKET_WIDTH) * _BUCKET_WIDTH
        buckets.setdefault(low, []).append(bool(r.get("win")))
    return [
        {
            "bucket_low": low,
            "bucket_high": low + _BUCKET_WIDTH,
            "n": len(wins),
            "win_rate": round(sum(wins) / len(wins), 4),
        }
        for low, wins in sorted(buckets.items())
    ]


def _factor_score(row: Mapping[str, object], factor: str) -> float | None:
    contributions = row.get("source_contributions")
    if not isinstance(contributions, Mapping):
        return None
    entry = contributions.get(factor)
    return _f(entry.get("score")) if isinstance(entry, Mapping) else None


def _ic(pairs: Sequence[tuple[float, float]]) -> float | None:
    if len(pairs) < _MIN_SAMPLES_FOR_IC:
        return None
    ic = spearman_ic([p[0] for p in pairs], [p[1] for p in pairs])
    return round(ic, 4) if ic is not None else None


def factor_ics(rows: Sequence[Mapping[str, object]]) -> dict[str, float | None]:
    """合成スコア・各ファクター・トレンドスコアと超過リターンの順位相関（サンプル不足は None）."""

    def pairs_for(extract: str) -> list[tuple[float, float]]:
        out: list[tuple[float, float]] = []
        for r in rows:
            excess = _f(r.get("excess_return"))
            if extract == "composite":
                score = _f(r.get("composite_score"))
            elif extract == "trend":
                score = _f(r.get("trend_score"))
            else:
                score = _factor_score(r, extract)
            if score is not None and excess is not None:
                out.append((score, excess))
        return out

    names = ["composite", *FACTOR_WEIGHTS, "trend"]
    return {name: _ic(pairs_for(name)) for name in names}


def _observed_factors(rows: Sequence[Mapping[str, object]]) -> tuple[str, ...]:
    """1 行でもスコアのあるファクター（リプレイでは入力の無いファンダメンタル・センチメントが外れる）."""
    return tuple(f for f in FACTOR_WEIGHTS if any(_factor_score(r, f) is not None for r in rows))


def _horizon_block(rows: Sequence[Mapping[str, object]]) -> dict[str, object]:
    return {
        "performance": performance_stats(rows),
        "calibration_table": composite_calibration_table(rows),
        "factor_ics": factor_ics(rows),
    }


async def compute_summary(run_id: str) -> dict[str, object]:
    """リプレイ台帳から学習結果サマリを作る（較正器はファイル保存するが本番には適用しない）."""
    horizons: dict[str, dict[str, object]] = {}
    ic_weights: dict[str, dict[str, float]] = {}
    calibration: dict[str, dict[str, object]] = {}
    for horizon_type, horizon_days in HORIZON_SETS.items():
        block: dict[str, object] = {}
        for h in horizon_days:
            rows = [
                r for r in await replay_db.list_resolved(run_id, horizon_days=h) if r["horizon_type"] == horizon_type
            ]
            block[str(h)] = _horizon_block(rows)
            if h == GATE_HORIZONS[horizon_type]:
                ic_weights[horizon_type] = ic_weights_from_rows(rows, factors=_observed_factors(rows))
                composites = [_f(r.get("composite_score")) for r in rows]
                valid = [(c, bool(r.get("win"))) for c, r in zip(composites, rows, strict=True) if c is not None]
                method = fit_and_save(
                    f"replay_composite_{horizon_type}",
                    h,
                    [c for c, _w in valid],
                    [w for _c, w in valid],
                )
                calibration[horizon_type] = {"horizon_days": h, "n": len(valid), "method": method}
        horizons[horizon_type] = block
    return {"horizons": horizons, "ic_weights": ic_weights, "calibration": calibration}
