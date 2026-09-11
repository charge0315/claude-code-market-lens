"""モデルレジストリ（登録・champion ブートストラップ）の検証（N1）."""

from __future__ import annotations

from pathlib import Path

from backend.services.db import model_registry_db
from backend.services.registry import model_registry as mr


async def test_ensure_registered_upserts_row(migrated_db: Path) -> None:
    await mr.ensure_registered("v1", lane="mid_term")
    row = await model_registry_db.get_model("v1")
    assert row is not None
    assert row["model_type"] == "recommender_llm_mid_term"
    assert row["ticker"] == "__pool__"

    # 2 回目は更新のみ（PK 衝突エラーにならない）。
    await mr.ensure_registered("v1", lane="mid_term", val_metrics={"win_rate": 0.5})
    row2 = await model_registry_db.get_model("v1")
    assert row2 is not None


async def test_bootstrap_sets_champion_only_once(migrated_db: Path) -> None:
    await mr.ensure_registered("v1", lane="mid_term")
    await mr.ensure_registered("v2", lane="mid_term")

    first = await mr.bootstrap_champion_if_missing("mid_term", "v1")
    assert first is True
    assert await model_registry_db.get_champion("mid_term") == "v1"

    # 既に champion がいるので v2 はブートストラップされない。
    second = await mr.bootstrap_champion_if_missing("mid_term", "v2")
    assert second is False
    assert await model_registry_db.get_champion("mid_term") == "v1"


async def test_lanes_are_independent(migrated_db: Path) -> None:
    await mr.ensure_registered("mid-v1", lane="mid_term")
    await mr.ensure_registered("short-v1", lane="short_term")
    await mr.bootstrap_champion_if_missing("mid_term", "mid-v1")
    await mr.bootstrap_champion_if_missing("short_term", "short-v1")

    assert await model_registry_db.get_champion("mid_term") == "mid-v1"
    assert await model_registry_db.get_champion("short_term") == "short-v1"

    versions = await model_registry_db.list_versions_by_model_type(mr.model_type_for_lane("mid_term"))
    assert versions == ["mid-v1"]
