"""昇格ゲート — champion / challenger の判定（N1）.

`plans/03_システム設計` §3.3。challenger（現行 champion 以外の登録済みバージョン）を、
そのバージョンが実際に生成し決着済みのピック実績で champion と比較する。Alpha Forge には
まだ shadow 推論（同一日に challenger 版を並走させる仕組み）が無いため、challenger の実績は
「そのバージョンが本番ピックとして生成し、後から決着した」実測値を使う（`is_shadow=0` の
`prediction_ledger` 行）。これは本物の walk-forward 実績であり、リークはない。

昇格条件（すべて満たす）:
- ペーパー日数（challenger の決着済みピックの発行日ユニーク数）>= `settings.paper_min_days`
- ホールドアウト指標（勝率）が champion を上回る
- 較正悪化なし（Brier が champion + `_CALIB_REGRESSION_EPS` 以内）
- ピック成績（平均 R 倍数）が champion 以上

昇格・却下は**提案のみ**。実際に champion を差し替えるのは `apply_promotion`（人手承認の
API 経由でのみ呼ばれる、`settings.model_auto_promote` は常に false 運用）。
"""

from __future__ import annotations

import json
import logging
import uuid
from dataclasses import dataclass

from backend.config import settings
from backend.services.db import model_registry_db, pick_outcome_db
from backend.services.learning.pool_model import POOL_LANE

logger = logging.getLogger(__name__)

_CALIB_REGRESSION_EPS = 0.01


def _f(value: object) -> float:
    return float(value) if isinstance(value, (int, float)) else 0.0


def _i(value: object) -> int:
    return int(value) if isinstance(value, (int, float, str)) else 0


@dataclass(frozen=True)
class ModelMetrics:
    """1 モデルバージョンの実測成績サマリ（決着済みピックから算出）."""

    sample_n: int
    win_rate: float | None
    avg_r_multiple: float | None
    brier: float | None
    paper_days: int


def _r_multiple(realized: float, entry: float, stop: float) -> float | None:
    risk = (entry - stop) / entry if entry else 0.0
    return realized / risk if risk > 0 else None


async def compute_model_metrics(model_version: str, *, horizon_days: int) -> ModelMetrics:
    """指定バージョンが生成し決着済みのピックから成績サマリを算出する."""
    rows = await pick_outcome_db.list_resolved_for_eval(horizon_days=horizon_days)
    rows = [r for r in rows if r["model_version"] == model_version]
    n = len(rows)
    if n == 0:
        return ModelMetrics(sample_n=0, win_rate=None, avg_r_multiple=None, brier=None, paper_days=0)

    wins = [1.0 if r["win"] else 0.0 for r in rows]
    win_rate = round(sum(wins) / n, 4)

    r_multiples = [
        rm for r in rows if (rm := _r_multiple(_f(r["realized_return"]), _f(r["entry"]), _f(r["stop"]))) is not None
    ]
    avg_r = round(sum(r_multiples) / len(r_multiples), 4) if r_multiples else None

    # Brier: 較正済み confidence（0-100）を確率とみなし、win を実測ラベルとして誤差を測る。
    brier = round(sum((_f(r["confidence"]) / 100.0 - w) ** 2 for r, w in zip(rows, wins, strict=True)) / n, 6)

    paper_days = len({str(r["issued_at"])[:10] for r in rows})
    return ModelMetrics(sample_n=n, win_rate=win_rate, avg_r_multiple=avg_r, brier=brier, paper_days=paper_days)


async def evaluate_promotion(lane: str, challenger_version: str, *, horizon_days: int) -> dict[str, object]:
    """challenger を champion と比較し、判定を `model_promotions` へ記録する（提案のみ）."""
    champion_version = await model_registry_db.get_champion(lane)
    challenger_metrics = await compute_model_metrics(challenger_version, horizon_days=horizon_days)

    rationale: dict[str, object] = {
        "challenger_metrics": vars(challenger_metrics),
        "champion_version": champion_version,
    }

    if champion_version is None or champion_version == challenger_version:
        # champion が未設定 or challenger 自身が champion（比較不要）。
        verdict = "hold"
        holdout_delta = 0.0
        calib_regressed = False
        paper_perf_delta = 0.0
        rationale["reason"] = "champion 未設定、または challenger が既に champion のため比較不要"
    else:
        champion_metrics = await compute_model_metrics(champion_version, horizon_days=horizon_days)
        rationale["champion_metrics"] = vars(champion_metrics)

        holdout_delta = (challenger_metrics.win_rate or 0.0) - (champion_metrics.win_rate or 0.0)
        calib_regressed = (
            challenger_metrics.brier is not None
            and champion_metrics.brier is not None
            and challenger_metrics.brier > champion_metrics.brier + _CALIB_REGRESSION_EPS
        )
        paper_perf_delta = (challenger_metrics.avg_r_multiple or 0.0) - (champion_metrics.avg_r_multiple or 0.0)

        if challenger_metrics.paper_days < settings.paper_min_days:
            verdict = "hold"
            rationale["reason"] = f"ペーパー日数 {challenger_metrics.paper_days} が基準 {settings.paper_min_days} 未満"
        elif holdout_delta > 0 and not calib_regressed and paper_perf_delta >= 0:
            verdict = "propose_promote"
            rationale["reason"] = "ホールドアウト超過・較正非劣化・ペーパー成績非劣化のすべてを満たした"
        elif holdout_delta < 0:
            verdict = "reject"
            rationale["reason"] = "ホールドアウト勝率が champion を下回った"
        else:
            verdict = "hold"
            rationale["reason"] = "較正悪化 or ペーパー成績劣化のため見送り"

    promotion_id = str(uuid.uuid4())
    await model_registry_db.insert_promotion(
        promotion_id=promotion_id,
        lane=lane,
        challenger_version=challenger_version,
        champion_version=champion_version,
        holdout_delta=round(holdout_delta, 4),
        calib_regressed=calib_regressed,
        paper_perf_delta=round(paper_perf_delta, 4),
        paper_days=challenger_metrics.paper_days,
        verdict=verdict,
        rationale=rationale,
    )
    logger.info("昇格ゲート: lane=%s challenger=%s verdict=%s", lane, challenger_version, verdict)
    return {"promotion_id": promotion_id, "verdict": verdict, "rationale": rationale}


def _val_metrics_of(row: dict[str, object]) -> dict[str, object]:
    """`model_registry` 行の `val_metrics`（JSON 文字列）を dict へ復元する."""
    raw = row.get("val_metrics")
    if not isinstance(raw, str) or not raw:
        return {}
    parsed = json.loads(raw)
    return parsed if isinstance(parsed, dict) else {}


async def evaluate_ml_pool_promotion(challenger_version: str) -> dict[str, object]:
    """lane="ml_pool"（断面プール XGBoost 分類器）専用の昇格判定.

    `evaluate_promotion` はピック単位の実測勝率（`prediction_ledger`）で champion/challenger を
    比較するが、プールモデルはパイプラインそのものではなく `recommender` の ML ファクター
    1つの寄与元にすぎず、ピックの勝敗は技術/ファンダメンタル/センチメントとの合成後にしか
    決着しない（プール単体の的中率をピック勝率から逆算できない）。代わりに学習時の held-out
    検証指標（`model_registry.val_metrics` に保存済みの AUC/Brier、`pool_training_service.
    train_pool_model` が算出）を champion と直接比較する。ペーパー日数の概念は適用しない
    （オフライン検証のみで判定する）。

    champion 未設定 / challenger が既に champion なら `hold`。held-out AUC が champion を
    上回り、かつ Brier が悪化していなければ `propose_promote`。AUC が下回れば `reject`、
    それ以外（Brier 悪化のみ）は `hold`。
    """
    champion_version = await model_registry_db.get_champion(POOL_LANE)
    challenger_row = await model_registry_db.get_model(challenger_version)
    if challenger_row is None:
        raise ValueError(f"model_registry に未登録のバージョンです: {challenger_version}")
    challenger_metrics = _val_metrics_of(challenger_row)

    rationale: dict[str, object] = {"champion_version": champion_version, "challenger_metrics": challenger_metrics}

    if champion_version is None or champion_version == challenger_version:
        verdict = "hold"
        auc_delta = 0.0
        brier_regressed = False
        rationale["reason"] = "champion 未設定、または challenger が既に champion のため比較不要"
    else:
        champion_row = await model_registry_db.get_model(champion_version)
        champion_metrics = _val_metrics_of(champion_row) if champion_row is not None else {}
        rationale["champion_metrics"] = champion_metrics

        auc_delta = _f(challenger_metrics.get("auc")) - _f(champion_metrics.get("auc"))
        challenger_brier = _f(challenger_metrics.get("brier"))
        champion_brier = _f(champion_metrics.get("brier"))
        brier_regressed = challenger_brier > champion_brier + _CALIB_REGRESSION_EPS

        if auc_delta > 0 and not brier_regressed:
            verdict = "propose_promote"
            rationale["reason"] = "held-out AUC が champion を上回り、Brier も非劣化"
        elif auc_delta < 0:
            verdict = "reject"
            rationale["reason"] = "held-out AUC が champion を下回った"
        else:
            verdict = "hold"
            rationale["reason"] = "Brier 悪化、または AUC 差なしのため見送り"

    promotion_id = str(uuid.uuid4())
    await model_registry_db.insert_promotion(
        promotion_id=promotion_id,
        lane=POOL_LANE,
        challenger_version=challenger_version,
        champion_version=champion_version,
        holdout_delta=round(auc_delta, 4),
        calib_regressed=brier_regressed,
        paper_perf_delta=0.0,
        paper_days=0,
        verdict=verdict,
        rationale=rationale,
    )
    logger.info("昇格ゲート(ml_pool): challenger=%s verdict=%s", challenger_version, verdict)
    return {"promotion_id": promotion_id, "verdict": verdict, "rationale": rationale}


async def apply_promotion(promotion_id: str) -> bool:
    """`propose_promote` かつ未適用の判定のみ、champion を差し替える（人手承認 API 専用）."""
    row = await model_registry_db.get_promotion(promotion_id)
    if row is None:
        return False
    if row["verdict"] != "propose_promote" or _i(row["applied"]) == 1:
        return False
    await model_registry_db.set_champion(str(row["lane"]), str(row["challenger_version"]), promoted_by="api_approval")
    await model_registry_db.mark_promotion_applied(promotion_id)
    logger.info("昇格ゲート: lane=%s を %s へ人手承認で昇格しました", row["lane"], row["challenger_version"])
    return True


_LANE_HORIZON: dict[str, int] = {"mid_term": 20, "short_term": 3}


async def evaluate_all_challengers() -> dict[str, str]:
    """全 lane について、champion 以外の登録済みバージョンを challenger として評価する（週次）.

    `mid_term`/`short_term`（LLM パイプライン）はピック実測（`evaluate_promotion`）、
    `ml_pool`（断面プール分類器）は held-out 検証指標（`evaluate_ml_pool_promotion`）で判定する
    — 判定方法は異なるが、どちらも提案のみで `apply_promotion` の人手承認を経ないと
    champion は変わらない。
    """
    from backend.services.registry.model_registry import model_type_for_lane

    results: dict[str, str] = {}
    for lane, horizon_days in _LANE_HORIZON.items():
        champion = await model_registry_db.get_champion(lane)
        versions = await model_registry_db.list_versions_by_model_type(model_type_for_lane(lane))
        for version in versions:
            if version == champion:
                continue
            outcome = await evaluate_promotion(lane, version, horizon_days=horizon_days)
            results[f"{lane}:{version}"] = str(outcome["verdict"])

    pool_champion = await model_registry_db.get_champion(POOL_LANE)
    pool_versions = await model_registry_db.list_versions_by_model_type(model_type_for_lane(POOL_LANE))
    for version in pool_versions:
        if version == pool_champion:
            continue
        pool_outcome = await evaluate_ml_pool_promotion(version)
        results[f"{POOL_LANE}:{version}"] = str(pool_outcome["verdict"])

    return results
