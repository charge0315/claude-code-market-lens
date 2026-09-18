"""panel_feature_service（断面特徴量の純関数・build_panel の I/O 層）のテスト.

Market Lens `backend/tests/test_panel_feature_service.py` から移植（インポート元のみ変更）。
ネットワーク・yfinance を一切使わない合成パネル・モック fetcher で検証する（🆕 P29 の
PIT 特徴量結合テストのみ `migrated_db` 隔離 DB を使う）。
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

import backend.services.learning.panel_feature_service as pfs
from backend.models.stocks import TickerInfo
from backend.services.learning.panel_feature_service import (
    add_cross_sectional_features,
    add_ticker_target_encoding,
    build_inference_row,
    build_panel,
    build_panel_context,
    compute_ticker_te_map,
    get_cached_panel_context,
)


def _panel() -> pd.DataFrame:
    """2営業日 × 4銘柄（2セクター）の最小パネル."""
    rows = [
        ("2026-09-01", "1001", "A", 0.01, 0.05, 0.02, 100.0, 0.010),
        ("2026-09-01", "1002", "A", 0.03, 0.09, -0.01, 300.0, 0.020),
        ("2026-09-01", "1003", "B", -0.02, 0.01, 0.00, 200.0, 0.015),
        ("2026-09-01", "1004", "B", 0.00, -0.04, 0.03, 400.0, 0.030),
        ("2026-09-02", "1001", "A", 0.02, 0.06, 0.01, 150.0, 0.011),
        ("2026-09-02", "1002", "A", -0.01, 0.02, -0.02, 350.0, 0.021),
        ("2026-09-02", "1003", "B", 0.04, 0.10, 0.05, 250.0, 0.016),
        ("2026-09-02", "1004", "B", 0.01, 0.03, 0.00, 450.0, 0.031),
    ]
    return pd.DataFrame(
        rows,
        columns=[
            "date",
            "code",
            "sector",
            "return_lag_1",
            "return_lag_5",
            "sma_20_diff",
            "dollar_volume",
            "volatility_20",
        ],
    )


# ---------------------------------------------------------------------------
# add_cross_sectional_features
# ---------------------------------------------------------------------------


def test_xs_rank_is_percentile_within_each_date() -> None:
    out = add_cross_sectional_features(_panel())

    d1 = out[out["date"] == "2026-09-01"].set_index("code")
    assert d1.loc["1003", "xs_rank_return_lag_1"] == pytest.approx(0.25)
    assert d1.loc["1002", "xs_rank_return_lag_1"] == pytest.approx(1.0)
    d2 = out[out["date"] == "2026-09-02"].set_index("code")
    assert d2.loc["1002", "xs_rank_return_lag_1"] == pytest.approx(0.25)


def test_xs_zscore_within_date_is_standardized() -> None:
    out = add_cross_sectional_features(_panel())
    d1 = out[out["date"] == "2026-09-01"]["xs_z_volatility_20"]
    assert d1.mean() == pytest.approx(0.0, abs=1e-9)
    assert d1.std() > 0.0


def test_sector_relative_uses_same_date_same_sector_median() -> None:
    out = add_cross_sectional_features(_panel())
    d1 = out[out["date"] == "2026-09-01"].set_index("code")
    assert d1.loc["1001", "sector_rel_return_lag_5"] == pytest.approx(0.05 - 0.07)
    assert d1.loc["1002", "sector_rel_return_lag_5"] == pytest.approx(0.09 - 0.07)
    assert d1.loc["1001", "sector_rank_return_lag_5"] == pytest.approx(0.5)
    assert d1.loc["1002", "sector_rank_return_lag_5"] == pytest.approx(1.0)


def test_market_and_breadth_are_constant_within_date() -> None:
    out = add_cross_sectional_features(_panel())
    d1 = out[out["date"] == "2026-09-01"]
    assert d1["market_return_lag_1"].nunique() == 1
    assert d1["market_return_lag_1"].iloc[0] == pytest.approx(np.mean([0.01, 0.03, -0.02, 0.00]))
    assert d1["breadth_pos"].iloc[0] == pytest.approx(0.5)


def test_missing_input_columns_are_skipped_without_error() -> None:
    thin = _panel()[["date", "code", "sector", "return_lag_1"]]
    out = add_cross_sectional_features(thin)
    assert "xs_rank_return_lag_1" in out.columns
    assert "xs_z_volatility_20" not in out.columns
    assert "sector_rel_return_lag_5" not in out.columns


def test_input_dataframe_is_not_mutated() -> None:
    panel = _panel()
    before = panel.copy()
    add_cross_sectional_features(panel)
    pd.testing.assert_frame_equal(panel, before)


def test_single_row_date_group_zscore_is_zero() -> None:
    one = _panel()[_panel()["code"] == "1001"].copy()
    out = add_cross_sectional_features(one)
    assert (out["xs_z_volatility_20"] == 0.0).all()


# ---------------------------------------------------------------------------
# add_ticker_target_encoding
# ---------------------------------------------------------------------------


def _labeled_panel(n_days: int = 40) -> pd.DataFrame:
    """1銘柄 = 一定の勝率でラベルが立つ、K-fold OOF 検証用の長パネル."""
    rng = np.random.default_rng(0)
    dates = pd.bdate_range("2026-01-01", periods=n_days).strftime("%Y-%m-%d")
    codes = {"7001": 0.8, "7002": 0.5, "7003": 0.2}
    rows = []
    for d in dates:
        for code, p in codes.items():
            rows.append((d, code, float(rng.random() < p)))
    return pd.DataFrame(rows, columns=["date", "code", "label"])


def test_target_encoding_adds_column_and_orders_by_true_rate() -> None:
    out = add_ticker_target_encoding(_labeled_panel())
    assert "ticker_te" in out.columns
    means = out.groupby("code")["ticker_te"].mean()
    assert means["7001"] > means["7002"] > means["7003"]


def test_target_encoding_is_oof_no_self_leakage() -> None:
    """ある銘柄の全行 label=1 でも、K-fold OOF なので te は 1.0 に張り付かず平滑化される."""
    panel = pd.DataFrame(
        {"date": [f"2026-01-{i + 1:02d}" for i in range(20)], "code": ["9999"] * 20, "label": [1.0] * 20}
    )
    other = pd.DataFrame(
        {"date": [f"2026-02-{i + 1:02d}" for i in range(20)], "code": ["0001"] * 20, "label": [0.0] * 20}
    )
    mixed = pd.concat([panel, other], ignore_index=True)
    out2 = add_ticker_target_encoding(mixed)
    te_9999 = out2[out2["code"] == "9999"]["ticker_te"].iloc[0]
    assert 0.5 < te_9999 < 1.0


def test_target_encoding_respects_train_mask_for_non_train_rows() -> None:
    panel = _labeled_panel(n_days=30)
    val_dates = set(sorted(panel["date"].unique())[-10:])
    train_mask = ~panel["date"].isin(val_dates)

    out = add_ticker_target_encoding(panel, train_mask=train_mask)

    for code in ("7001", "7002", "7003"):
        val_te = out[(out["code"] == code) & (out["date"].isin(val_dates))]["ticker_te"]
        assert val_te.nunique() == 1
    val_means = out[out["date"].isin(val_dates)].groupby("code")["ticker_te"].first()
    assert val_means["7001"] > val_means["7002"] > val_means["7003"]


def test_target_encoding_unknown_ticker_in_val_gets_global_mean() -> None:
    train = _labeled_panel(n_days=20)
    newcomer = pd.DataFrame({"date": ["2026-03-02"] * 3, "code": ["8888"] * 3, "label": [1.0, 1.0, 1.0]})
    panel = pd.concat([train, newcomer], ignore_index=True)
    train_mask = panel["code"] != "8888"

    out = add_ticker_target_encoding(panel, train_mask=train_mask)

    global_mean = float(out.loc[train_mask, "label"].mean())
    te_8888 = out[out["code"] == "8888"]["ticker_te"]
    assert te_8888.nunique() == 1
    assert te_8888.iloc[0] == pytest.approx(global_mean, abs=1e-9)


# ---------------------------------------------------------------------------
# build_panel（I/O 層 — fetcher は全てモック）
# ---------------------------------------------------------------------------


def _ohlcv(seed: int, n: int = 200, tz: str | None = None) -> pd.DataFrame:
    """200 営業日の合成 OHLCV（DatetimeIndex）。tz を渡すと tz-aware にする
    （`get_stock_data` が返す Asia/Tokyo インデックスを模擬）。"""
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range("2025-01-01", periods=n, tz=tz)
    close = 1000.0 * np.cumprod(1.0 + rng.normal(0.0005, 0.02, size=n))
    high = close * (1.0 + np.abs(rng.normal(0.0, 0.01, size=n)))
    low = close * (1.0 - np.abs(rng.normal(0.0, 0.01, size=n)))
    return pd.DataFrame(
        {
            "Open": close * (1.0 + rng.normal(0.0, 0.005, size=n)),
            "High": np.maximum(high, close),
            "Low": np.minimum(low, close),
            "Close": close,
            "Volume": rng.integers(1_000_000, 5_000_000, size=n).astype(float),
        },
        index=idx,
    )


_UNIVERSE = [
    TickerInfo(code="7203", name="A社", sector="輸送用機器"),
    TickerInfo(code="6758", name="B社", sector="電気機器"),
    TickerInfo(code="6861", name="C社", sector="電気機器"),
    TickerInfo(code="9984", name="D社", sector="情報・通信業"),
]
_AS_OF = [pd.bdate_range("2025-01-01", periods=200)[100].strftime("%Y-%m-%d")]


def _fake_price_loader(code: str) -> pd.DataFrame | None:
    seeds = {"7203": 1, "6758": 2, "6861": 3, "9984": 4}
    return _ohlcv(seeds[code]) if code in seeds else None


async def _fake_forward_returns(as_of: str) -> dict[str, float]:
    tracked = {"72030": 0.12, "67580": -0.05, "68610": 0.03, "99840": 0.00}
    filler = {f"{10000 + i}": (i - 15) * 0.01 for i in range(30)}
    return {**tracked, **filler}


@pytest.mark.asyncio
async def test_build_panel_shape_and_columns() -> None:
    panel = await build_panel(
        _AS_OF, universe=_UNIVERSE, price_loader=_fake_price_loader, forward_return_loader=_fake_forward_returns
    )

    assert not panel.empty
    assert set(panel["code"]) == {"7203", "6758", "6861", "9984"}
    assert (panel["date"] == _AS_OF[0]).all()
    for col in ("return_lag_1", "return_lag_5", "sma_20_diff", "dollar_volume", "sector", "label"):
        assert col in panel.columns
    for col in ("xs_rank_return_lag_1", "xs_z_volatility_20", "sector_rel_return_lag_5", "breadth_pos"):
        assert col in panel.columns
    assert "ticker_te" not in panel.columns


@pytest.mark.asyncio
async def test_build_panel_labels_from_cross_sectional_rank() -> None:
    panel = await build_panel(
        _AS_OF, universe=_UNIVERSE, price_loader=_fake_price_loader, forward_return_loader=_fake_forward_returns
    )

    by_code = panel.set_index("code")["label"]
    assert by_code["7203"] == 1.0
    assert by_code["6758"] == 0.0
    assert by_code["9984"] == 0.0


@pytest.mark.asyncio
async def test_build_panel_skips_tickers_without_price_data() -> None:
    universe = [*_UNIVERSE, TickerInfo(code="0000", name="なし", sector="X")]
    panel = await build_panel(
        _AS_OF, universe=universe, price_loader=_fake_price_loader, forward_return_loader=_fake_forward_returns
    )
    assert "0000" not in set(panel["code"])


@pytest.mark.asyncio
async def test_build_panel_empty_when_no_frames() -> None:
    panel = await build_panel(
        _AS_OF,
        universe=[TickerInfo(code="0000", name="なし", sector="X")],
        price_loader=lambda _c: None,
        forward_return_loader=_fake_forward_returns,
    )
    assert panel.empty


# ---------------------------------------------------------------------------
# PanelContext / build_panel_context / build_inference_row
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_build_panel_context_and_inference_row_match_build_panel_columns() -> None:
    as_of = _AS_OF[0]
    ctx = await build_panel_context(as_of, universe=_UNIVERSE, price_loader=_fake_price_loader)
    assert ctx.as_of == as_of
    assert set(ctx.frame.index) == {"7203", "6758", "6861", "9984"}

    panel = await build_panel(
        [as_of], universe=_UNIVERSE, price_loader=_fake_price_loader, forward_return_loader=_fake_forward_returns
    )
    panel_cols = set(panel.columns) - {"label", "fwd_return"}

    row = build_inference_row("7203", ctx, ticker_te_map={"7203": 0.7, "__global__": 0.4})
    assert row is not None
    assert len(row) == 1
    assert panel_cols <= set(row.columns)
    assert row["code"].iloc[0] == "7203"
    assert row["ticker_te"].iloc[0] == pytest.approx(0.7)
    p7203 = panel[panel["code"] == "7203"].iloc[0]
    assert row["xs_rank_return_lag_1"].iloc[0] == pytest.approx(p7203["xs_rank_return_lag_1"])
    assert row["sector_rel_return_lag_5"].iloc[0] == pytest.approx(p7203["sector_rel_return_lag_5"])


@pytest.mark.asyncio
async def test_build_inference_row_ticker_te_fallbacks() -> None:
    ctx = await build_panel_context(_AS_OF[0], universe=_UNIVERSE, price_loader=_fake_price_loader)

    r1 = build_inference_row("6758", ctx, ticker_te_map={"__global__": 0.42})
    assert r1 is not None and r1["ticker_te"].iloc[0] == pytest.approx(0.42)
    r2 = build_inference_row("6758", ctx, ticker_te_map=None)
    assert r2 is not None and r2["ticker_te"].iloc[0] == pytest.approx(0.5)
    assert build_inference_row("0000", ctx) is None


@pytest.mark.asyncio
async def test_build_panel_matches_tz_aware_price_index() -> None:
    """`get_stock_data` は Asia/Tokyo の tz-aware インデックスを返す。naive な as_of 文字列と
    日付で突き合うこと（tz-aware Timestamp vs naive Timestamp の集合照合だと 0 行になる回帰）。"""

    def tz_loader(code: str) -> pd.DataFrame:
        return _ohlcv({"7203": 1, "6758": 2, "6861": 3, "9984": 4}[code], tz="Asia/Tokyo")

    as_of = _AS_OF[0]

    panel = await build_panel(
        [as_of], universe=_UNIVERSE, price_loader=tz_loader, forward_return_loader=_fake_forward_returns
    )
    assert not panel.empty
    assert set(panel["code"]) == {"7203", "6758", "6861", "9984"}
    assert (panel["date"] == as_of).all()

    ctx = await build_panel_context(as_of, universe=_UNIVERSE, price_loader=tz_loader)
    assert set(ctx.frame.index) == {"7203", "6758", "6861", "9984"}


@pytest.mark.asyncio
async def test_build_panel_context_empty_when_no_prices() -> None:
    ctx = await build_panel_context(
        _AS_OF[0], universe=[TickerInfo(code="0000", name="x", sector="X")], price_loader=lambda _c: None
    )
    assert ctx.frame.empty
    assert build_inference_row("0000", ctx) is None


# ---------------------------------------------------------------------------
# PIT（point-in-time）特徴量の結合（🆕 P29）
# ---------------------------------------------------------------------------


async def _seed_pit_fundamental(snapshot_date: str, codes: list[str]) -> None:
    from backend.services.db import pit_snapshot_db

    for i, code in enumerate(codes):
        await pit_snapshot_db.upsert_fundamental_snapshot(
            snapshot_date=snapshot_date,
            code=code,
            source="vault_frontmatter",
            data_as_of=snapshot_date,
            per_forecast=10.0 + i,
            pbr=1.0 + i * 0.1,
            roe=0.1 + i * 0.01,
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


async def test_build_panel_is_unaffected_when_pit_features_disabled(migrated_db: Path) -> None:
    """既定（`PIT_FEATURES_ENABLED=false`）では PIT 列も `attrs["pit_coverage"]` も一切付かないこと."""
    panel = await build_panel(
        _AS_OF, universe=_UNIVERSE, price_loader=_fake_price_loader, forward_return_loader=_fake_forward_returns
    )
    assert "per_forecast" not in panel.columns
    assert "has_pit_fundamental" not in panel.columns
    assert "pit_coverage" not in panel.attrs


async def test_build_panel_attaches_pit_fundamental_when_coverage_meets_gate(
    migrated_db: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from backend import config

    await _seed_pit_fundamental(_AS_OF[0], [t.code for t in _UNIVERSE])
    monkeypatch.setattr(
        pfs,
        "settings",
        config.settings.model_copy(
            update={"pit_features_enabled": True, "pit_min_coverage_days": 1, "pit_min_coverage_ratio": 1.0}
        ),
    )

    panel = await build_panel(
        _AS_OF, universe=_UNIVERSE, price_loader=_fake_price_loader, forward_return_loader=_fake_forward_returns
    )

    assert (panel["has_pit_fundamental"] == 1).all()
    assert (panel["per_forecast"] > 0).all()
    # 断面ランク列（相対位置）が PIT 列にも付いていること（§3.7.3）。
    assert "xs_rank_per_forecast" in panel.columns
    assert "sector_rel_roe" in panel.columns
    assert panel.attrs["pit_coverage"]["pit_fundamental"]["included"] is True


async def test_build_panel_drops_pit_fundamental_columns_when_coverage_gate_not_met(
    migrated_db: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """PIT 台帳が空（被覆率ゲート未達）のときは列ごと落として学習対象から除外すること.

    薄い列を無理に食わせると「欠損 = 古い期間」という時間軸を学習してしまう、という
    §3.7.4 の理由に対応する回帰テスト。"""
    from backend import config

    monkeypatch.setattr(pfs, "settings", config.settings.model_copy(update={"pit_features_enabled": True}))

    panel = await build_panel(
        _AS_OF, universe=_UNIVERSE, price_loader=_fake_price_loader, forward_return_loader=_fake_forward_returns
    )

    assert "per_forecast" not in panel.columns
    assert "has_pit_fundamental" not in panel.columns
    assert "xs_rank_per_forecast" not in panel.columns
    report = panel.attrs["pit_coverage"]["pit_fundamental"]
    assert report["included"] is False
    assert report["covered_days"] == 0


# ---------------------------------------------------------------------------
# get_cached_panel_context
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_cached_panel_context_builds_once_per_as_of(monkeypatch: pytest.MonkeyPatch) -> None:
    """同じ as_of の2回目以降はキャッシュ値を返し build_panel_context を再実行しない."""
    pfs._context_cache.clear()
    calls: list[str] = []

    async def _fake_build(as_of: str) -> object:
        calls.append(as_of)
        return pfs.PanelContext(as_of=as_of, frame=pd.DataFrame({"x": [1.0]}, index=pd.Index(["7203"], name="code")))

    monkeypatch.setattr(pfs, "build_panel_context", _fake_build)
    try:
        a1 = await get_cached_panel_context("2026-09-07")
        a2 = await get_cached_panel_context("2026-09-07")
        assert a1 is a2
        assert calls == ["2026-09-07"]

        await get_cached_panel_context("2026-09-08")
        assert calls == ["2026-09-07", "2026-09-08"]
        assert set(pfs._context_cache) == {"2026-09-08"}
    finally:
        pfs._context_cache.clear()


# ---------------------------------------------------------------------------
# compute_ticker_te_map
# ---------------------------------------------------------------------------


def test_compute_ticker_te_map_has_global_and_orders_by_rate() -> None:
    te_map = compute_ticker_te_map(_labeled_panel(n_days=40))

    assert "__global__" in te_map
    assert set(te_map) == {"7001", "7002", "7003", "__global__"}
    assert te_map["7001"] > te_map["7002"] > te_map["7003"]
    assert te_map["7001"] < 0.8 and te_map["7003"] > 0.2


def test_compute_ticker_te_map_respects_train_mask() -> None:
    panel = _labeled_panel(n_days=30)
    val_dates = set(sorted(panel["date"].unique())[-10:])
    train_mask = ~panel["date"].isin(val_dates)

    te_map = compute_ticker_te_map(panel, train_mask=train_mask)
    assert set(te_map) == {"7001", "7002", "7003", "__global__"}
    assert all(0.0 <= v <= 1.0 for v in te_map.values())
