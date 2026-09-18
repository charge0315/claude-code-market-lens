"""PIT 特徴量の as-of backward 結合の検証（🆕 P29）.

最重要テストは `test_never_joins_a_future_snapshot_into_a_past_panel_row`
（`plans/04_タスクリスト.md` P29 完了条件 (2)）: 未来日の PIT スナップショットが
過去の学習行へ混入しないことを構造的に保証する。
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from backend.services.db import pit_snapshot_db
from backend.services.learning import pit_feature_service as pfs

_TOLERANCE = 5


async def _upsert_fund(*, snapshot_date: str, code: str, per_forecast: float) -> None:
    await pit_snapshot_db.upsert_fundamental_snapshot(
        snapshot_date=snapshot_date,
        code=code,
        source="vault_frontmatter",
        data_as_of=None,
        per_forecast=per_forecast,
        pbr=None,
        roe=None,
        equity_ratio=None,
        dividend_yield_forecast=None,
        eps_forecast=None,
        bps=None,
        market_cap_oku=None,
        shares_outstanding=None,
        last_earnings_date=None,
        last_earnings_type=None,
        sector33=None,
        sector17=None,
        scale_cat=None,
        market=None,
        extra=None,
        created_at=f"{snapshot_date}T16:45:00+09:00",
    )


def _panel(rows: list[tuple[str, str]]) -> pd.DataFrame:
    return pd.DataFrame({"date": [d for d, _ in rows], "code": [c for _, c in rows]})


async def test_never_joins_a_future_snapshot_into_a_past_panel_row(migrated_db: Path) -> None:
    """未来日（学習行の `date` より後）にしか PIT 行が無い場合、結合されず NaN のままであること.

    Vault `Tickers/*.md` は「現在値」の上書きファイルであり、これを過去の学習行へそのまま
    結合すると未来情報の漏洩（lookahead bias）になる — この結合ロジックの存在理由そのもの。
    """
    await _upsert_fund(snapshot_date="2026-01-10", code="7203", per_forecast=99.0)  # 未来（学習行より後）

    panel = _panel([("2026-01-05", "7203")])
    out = await pfs.attach_pit_fundamental_features(panel, tolerance_bdays=_TOLERANCE)

    assert out.loc[0, "has_pit_fundamental"] == 0
    assert pd.isna(out.loc[0, "per_forecast"])


async def test_uses_latest_snapshot_on_or_before_as_of_date(migrated_db: Path) -> None:
    await _upsert_fund(snapshot_date="2026-01-01", code="7203", per_forecast=10.0)
    await _upsert_fund(snapshot_date="2026-01-04", code="7203", per_forecast=12.0)
    await _upsert_fund(snapshot_date="2026-01-10", code="7203", per_forecast=99.0)  # 未来分（無視されること）

    panel = _panel([("2026-01-05", "7203")])
    out = await pfs.attach_pit_fundamental_features(panel, tolerance_bdays=_TOLERANCE)

    assert out.loc[0, "per_forecast"] == 12.0  # 直近の過去分（01-04）が採用される
    assert out.loc[0, "has_pit_fundamental"] == 1
    assert out.loc[0, "pit_fundamental_staleness_days"] == 1


async def test_same_day_snapshot_is_joined(migrated_db: Path) -> None:
    await _upsert_fund(snapshot_date="2026-01-05", code="7203", per_forecast=15.0)

    panel = _panel([("2026-01-05", "7203")])
    out = await pfs.attach_pit_fundamental_features(panel, tolerance_bdays=_TOLERANCE)

    assert out.loc[0, "per_forecast"] == 15.0
    assert out.loc[0, "pit_fundamental_staleness_days"] == 0


async def test_snapshot_older_than_tolerance_is_dropped_as_stale(migrated_db: Path) -> None:
    await _upsert_fund(snapshot_date="2025-11-01", code="7203", per_forecast=10.0)  # 60日以上前

    panel = _panel([("2026-01-05", "7203")])
    out = await pfs.attach_pit_fundamental_features(panel, tolerance_bdays=_TOLERANCE)

    assert out.loc[0, "has_pit_fundamental"] == 0
    assert pd.isna(out.loc[0, "per_forecast"])


async def test_join_is_per_code_and_preserves_original_row_order(migrated_db: Path) -> None:
    await _upsert_fund(snapshot_date="2026-01-04", code="7203", per_forecast=12.0)
    await _upsert_fund(snapshot_date="2026-01-04", code="9984", per_forecast=30.0)

    panel = _panel([("2026-01-05", "9984"), ("2026-01-05", "7203")])
    out = await pfs.attach_pit_fundamental_features(panel, tolerance_bdays=_TOLERANCE)

    # 元の行順（9984 が先）が保たれ、コードを取り違えていないこと。
    assert list(out["code"]) == ["9984", "7203"]
    assert out.loc[0, "per_forecast"] == 30.0
    assert out.loc[1, "per_forecast"] == 12.0


async def test_no_snapshots_at_all_returns_all_nan_without_error(migrated_db: Path) -> None:
    panel = _panel([("2026-01-05", "7203"), ("2026-01-06", "9984")])
    out = await pfs.attach_pit_fundamental_features(panel, tolerance_bdays=_TOLERANCE)

    assert out["has_pit_fundamental"].tolist() == [0, 0]
    assert out["per_forecast"].isna().all()


async def test_empty_panel_returns_empty_frame_with_expected_columns(migrated_db: Path) -> None:
    panel = pd.DataFrame({"date": pd.Series(dtype="object"), "code": pd.Series(dtype="object")})
    out = await pfs.attach_pit_fundamental_features(panel, tolerance_bdays=_TOLERANCE)

    assert out.empty
    assert "has_pit_fundamental" in out.columns
    assert "per_forecast" in out.columns


async def test_attach_pit_sentiment_features_keyword(migrated_db: Path) -> None:
    await pit_snapshot_db.upsert_sentiment_snapshot(
        snapshot_date="2026-01-04",
        code="7203",
        source="keyword",
        news_count=5,
        keyword_score=0.7,
        created_at="2026-01-04T16:50:00+09:00",
    )

    panel = _panel([("2026-01-05", "7203")])
    out = await pfs.attach_pit_sentiment_features(panel, source="keyword", tolerance_bdays=_TOLERANCE)

    assert out.loc[0, "keyword_score"] == 0.7
    assert out.loc[0, "has_pit_sentiment_keyword"] == 1


async def test_attach_pit_sentiment_features_llm_future_snapshot_not_joined(migrated_db: Path) -> None:
    """センチメントも同じ不変条件（未来の LLM 判定を過去行へ漏らさない）を満たすこと."""
    await pit_snapshot_db.upsert_sentiment_snapshot(
        snapshot_date="2026-01-10",
        code="7203",
        source="llm",
        news_count=2,
        llm_sentiment_score=0.9,
        llm_impact_score=80.0,
        llm_confidence=90.0,
        created_at="2026-01-10T08:50:00+09:00",
    )

    panel = _panel([("2026-01-05", "7203")])
    out = await pfs.attach_pit_sentiment_features(panel, source="llm", tolerance_bdays=_TOLERANCE)

    assert out.loc[0, "has_pit_sentiment_llm"] == 0
    assert pd.isna(out.loc[0, "llm_sentiment_score"])


@pytest.mark.parametrize("source", ["keyword", "llm"])
async def test_attach_pit_sentiment_features_no_rows(migrated_db: Path, source: str) -> None:
    panel = _panel([("2026-01-05", "7203")])
    out = await pfs.attach_pit_sentiment_features(panel, source=source, tolerance_bdays=_TOLERANCE)
    assert out[f"has_pit_sentiment_{source}"].tolist() == [0]


# --- 被覆率ゲート（ブートストラップ、`plans/03` §3.7.4）---


def test_compute_group_coverage_all_covered() -> None:
    panel = pd.DataFrame(
        {"date": ["2026-01-05", "2026-01-06", "2026-01-06"], "code": ["7203", "7203", "9984"], "has_x": [1, 1, 1]}
    )
    coverage = pfs.compute_group_coverage(panel, group="x", has_col="has_x")
    assert coverage.covered_days == 2
    assert coverage.total_days == 2
    assert coverage.covered_ratio == 1.0
    assert coverage.meets_gate(min_coverage_days=2, min_coverage_ratio=1.0)


def test_compute_group_coverage_partial() -> None:
    panel = pd.DataFrame(
        {"date": ["2026-01-05", "2026-01-06", "2026-01-06"], "code": ["7203", "7203", "9984"], "has_x": [0, 1, 0]}
    )
    coverage = pfs.compute_group_coverage(panel, group="x", has_col="has_x")
    assert coverage.covered_days == 1  # 01-06 のみ（1行でも非欠損があれば「被覆」扱い）
    assert coverage.covered_ratio == pytest.approx(1 / 3)
    assert not coverage.meets_gate(min_coverage_days=60, min_coverage_ratio=0.5)


def test_compute_group_coverage_empty_panel() -> None:
    panel = pd.DataFrame({"date": pd.Series(dtype="object"), "code": pd.Series(dtype="object")})
    coverage = pfs.compute_group_coverage(panel, group="x", has_col="has_x")
    assert coverage == pfs.PitCoverage(group="x", covered_days=0, total_days=0, covered_ratio=0.0)
