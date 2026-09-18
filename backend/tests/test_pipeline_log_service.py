"""日次パイプラインログ（🆕 P30）の生成・保存の検証."""

from __future__ import annotations

from pathlib import Path

from backend.models.pick import LedgerEntry, SubScores
from backend.services.db import eval_db, model_registry_db, pick_outcome_db
from backend.services.db.inference_trace_db import insert_trace_event
from backend.services.db.pick_pool_snapshot_db import insert_pool_snapshots
from backend.services.ledger import prediction_ledger as pl
from backend.services.vault_report.pipeline_log_generator import build_pipeline_log_markdown
from backend.services.vault_report.pipeline_log_service import generate_pipeline_log_for_date
from backend.tests.conftest import VaultDirs

_DATE = "2026-09-18"


def _ledger_entry(pick_id: str) -> LedgerEntry:
    return LedgerEntry(
        pick_id=pick_id,
        run_id="batch-1",
        issued_at=f"{_DATE}T07:30:00+09:00",
        horizon_type="mid_term",
        symbol="7203",
        direction="bullish",
        entry=1002.0,
        stop=985.0,
        target=1050.0,
        sub_scores=SubScores(technical=60.0, trend=55.0, fundamental=55.0, sentiment=50.0),
        composite_score=62.0,
        concordance=0.67,
        confidence_raw=72.0,
        confidence=72.0,
        confidence_bucket="high",
        feature_snapshot={},
        rationale_struct={},
        rationale_text="反発余地あり",
        model_version="test-model",
        source_contributions={},
        created_at=f"{_DATE}T07:30:05+09:00",
    )


async def _seed_pool_and_traces() -> None:
    await insert_pool_snapshots(
        [
            {
                "batch_run_id": "batch-1",
                "horizon_type": "mid_term",
                "issued_at": f"{_DATE}T07:30:00+09:00",
                "symbol": "7203",
                "composite_score": 62.0,
                "direction": "bullish",
                "concordance": 0.67,
                "score_breakdown": {"technical": 60.0, "fundamental": 55.0, "sentiment": 50.0},
                "trend_score": 55.0,
                "ml_prediction_rate": 0.6,
                "is_shortlisted": True,
            },
            {
                "batch_run_id": "batch-1",
                "horizon_type": "mid_term",
                "issued_at": f"{_DATE}T07:30:00+09:00",
                "symbol": "6758",
                "composite_score": 40.0,
                "direction": "neutral",
                "concordance": 0.3,
                "score_breakdown": {"technical": 45.0, "fundamental": 40.0, "sentiment": None},
                "trend_score": 42.0,
                "ml_prediction_rate": None,
                "is_shortlisted": False,
            },
        ]
    )
    # 採用（7203）: collect → verify まで通し、pick_id を紐付ける。
    await insert_trace_event(
        run_id="run-7203",
        symbol="7203",
        horizon_type="mid_term",
        status="running",
        stage="collect",
        stage_status="done",
        stage_seq=1,
        payload={"current_price": 1000.0},
        started_at=f"{_DATE}T07:30:10+09:00",
    )
    await insert_trace_event(
        run_id="run-7203",
        symbol="7203",
        horizon_type="mid_term",
        status="done",
        stage="verify",
        stage_status="done",
        stage_seq=2,
        payload={"confidence": 72.0},
        started_at=f"{_DATE}T07:30:10+09:00",
        finished_at=f"{_DATE}T07:30:20+09:00",
        pick_id="pick-1",
    )
    # 却下（6758）: verify で実測勝率ゲートに引っかかった想定。
    await insert_trace_event(
        run_id="run-6758",
        symbol="6758",
        horizon_type="mid_term",
        status="rejected",
        stage="verify",
        stage_status="failed",
        stage_seq=1,
        payload={"reason": "実測勝率ゲート: mid/neutral コホート勝率 30%（n=25）が基準 45% 未満"},
        started_at=f"{_DATE}T07:30:10+09:00",
    )
    await pl.insert_pick(_ledger_entry("pick-1"))


async def test_build_pipeline_log_markdown_includes_all_sections(migrated_db: Path, vault_dirs: VaultDirs) -> None:
    await _seed_pool_and_traces()
    await pick_outcome_db.upsert_outcome(
        pick_id="pick-1",
        horizon_days=20,
        resolved_at=f"{_DATE}T16:38:00+09:00",
        realized_return=0.05,
        win=True,
        hit_stop=False,
        hit_target=True,
        first_hit="target",
        mfe=0.06,
        mae=-0.01,
        benchmark_return=0.01,
        excess_return=0.04,
        confidence_bucket="high",
        direction="bullish",
    )
    await eval_db.insert_eval_snapshot(
        scope="mid_term",
        metric_name="win_rate",
        metric_value=0.55,
        sample_n=20,
        horizon_days=20,
        computed_at=f"{_DATE}T16:48:00+09:00",
    )
    await model_registry_db.upsert_model(version="baseline-2026-09-11", model_type="mid_term")
    await model_registry_db.upsert_model(version="challenger-1", model_type="mid_term")
    await model_registry_db.insert_promotion(
        promotion_id="promo-1",
        lane="mid_term",
        challenger_version="challenger-1",
        champion_version="baseline-2026-09-11",
        holdout_delta=0.05,
        calib_regressed=False,
        paper_perf_delta=0.1,
        paper_days=25,
        verdict="propose_promote",
        rationale={"reason": "ホールドアウト超過・較正非劣化・ペーパー成績非劣化のすべてを満たした"},
        evaluated_at=f"{_DATE}T03:45:00+09:00",
    )
    await model_registry_db.set_champion("mid_term", "challenger-1", promoted_by="api_approval")

    markdown, counts = await build_pipeline_log_markdown(_DATE)

    assert counts == {
        "candidate_count": 2,
        "shortlisted_count": 1,
        "ledger_count": 1,
        "resolved_outcome_count": 1,
        "eval_metric_count": 1,
        "promotion_count": 1,
        "champion_swap_count": 1,
    }
    assert "7203" in markdown and "6758" in markdown
    assert "反発余地あり" in markdown  # LLM見解（採用ピックの rationale_text）
    assert "実測勝率ゲート" in markdown  # 却下理由（verify ステージの reason）
    assert "entry=1002.0" in markdown  # 3値ブラケット
    assert "win_rate" in markdown  # 評価指標
    assert "昇格提案" in markdown  # 再学習・昇格ゲート結果
    assert "challenger-1" in markdown  # champion 入れ替え


async def test_generate_pipeline_log_for_date_writes_file(migrated_db: Path, vault_dirs: VaultDirs) -> None:
    await _seed_pool_and_traces()

    result = await generate_pipeline_log_for_date(_DATE)

    expected_path = vault_dirs.daily / "AlphaForge" / _DATE / "pipeline_log.md"
    assert Path(result.log_path) == expected_path
    assert expected_path.is_file()
    assert result.candidate_count == 2
    assert result.shortlisted_count == 1
    assert result.ledger_count == 1


async def test_build_pipeline_log_markdown_handles_empty_date(migrated_db: Path) -> None:
    markdown, counts = await build_pipeline_log_markdown("2099-01-01")

    assert all(v == 0 for v in counts.values())
    assert "該当データなし" in markdown
    assert "本日の確定ピックなし" in markdown
