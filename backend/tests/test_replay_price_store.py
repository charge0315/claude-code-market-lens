"""過去日リプレイの価格ストア（🆕 P37）の検証.

最重要の不変条件は「リプレイ日 D の時点では D より後のバーを一切読めない」こと。
ここが破れると、再現したピックの成績がそのまま未来リーク込みの楽観値になる。
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from backend.services.replay import price_store as ps


def _bar(date: str, code: str, close: float, volume: float = 1000.0) -> dict[str, object]:
    return {
        "Date": date,
        "Code": code,
        "AdjO": close,
        "AdjH": close + 1,
        "AdjL": close - 1,
        "AdjC": close,
        "AdjVo": volume,
    }


_DAYS = ["2021-10-01", "2021-10-04", "2021-10-05", "2021-10-06"]


def _store() -> ps.PriceStore:
    rows = [_bar(d, "72030", 100.0 + i) for i, d in enumerate(_DAYS)]
    rows += [_bar(d, "13060", 2000.0 + i) for i, d in enumerate(_DAYS)]
    rows.append({**_bar("2021-10-04", "99990", 0.0), "AdjC": None})  # 売買不成立（終値なし）
    return ps.PriceStore(pd.DataFrame(rows))


def test_history_never_includes_rows_after_as_of() -> None:
    view = _store().view("2021-10-04")

    hist = view.history("7203")

    assert [ts.strftime("%Y-%m-%d") for ts in hist.index] == ["2021-10-01", "2021-10-04"]
    assert list(hist.columns) == ["Open", "High", "Low", "Close", "Volume"]
    assert hist["Close"].iloc[-1] == 101.0


def test_history_returns_a_copy_that_cannot_leak_future_rows() -> None:
    store = _store()
    hist = store.view("2021-10-04").history("7203")
    hist.loc[pd.Timestamp("2021-10-05")] = [0.0, 0.0, 0.0, 0.0, 0.0]

    assert len(store.view("2021-10-04").history("7203")) == 2


def test_history_lookback_limits_rows() -> None:
    hist = _store().view("2021-10-06").history("7203", lookback_rows=2)

    assert [ts.strftime("%Y-%m-%d") for ts in hist.index] == ["2021-10-05", "2021-10-06"]


def test_bars_on_future_date_raises() -> None:
    view = _store().view("2021-10-04")

    assert {b["Code"] for b in view.bars_on("2021-10-04")} == {"72030", "13060"}
    with pytest.raises(ps.FutureDataAccessError):
        view.bars_on("2021-10-05")


def test_bars_on_skips_rows_without_close() -> None:
    codes = {b["Code"] for b in _store().view("2021-10-04").bars_on("2021-10-04")}

    assert "99990" not in codes


def test_view_rejects_non_trading_or_out_of_range_date() -> None:
    with pytest.raises(ValueError):
        _store().view("2021-10-02")  # 土曜


def test_trading_dates_and_previous_trading_date() -> None:
    store = _store()

    assert store.trading_dates == _DAYS
    assert store.previous_trading_date("2021-10-04") == "2021-10-01"
    assert store.previous_trading_date("2021-10-01") is None


def test_unknown_code_returns_empty_history() -> None:
    assert _store().view("2021-10-06").history("0000").empty


async def test_ensure_bar_cache_fetches_missing_days_only_and_marks_holidays(tmp_path: Path) -> None:
    """未取得日だけを取得し、非営業日（空応答）も空ファイルとして記録して再取得しない."""
    calls: list[str] = []

    async def fake_fetch(date: str) -> list[dict[str, object]]:
        calls.append(date)
        return [] if date == "2021-10-04" else [_bar(date, "72030", 100.0)]

    await ps.ensure_bar_cache("2021-10-01", "2021-10-05", cache_dir=tmp_path, fetch=fake_fetch)
    await ps.ensure_bar_cache("2021-10-01", "2021-10-05", cache_dir=tmp_path, fetch=fake_fetch)

    # 土日（10/2・10/3）は平日でないため問い合わせない。2 回目は全日キャッシュ済み。
    assert calls == ["2021-10-01", "2021-10-04", "2021-10-05"]

    store = ps.load_price_store(tmp_path, "2021-10-01", "2021-10-05")
    assert store.trading_dates == ["2021-10-01", "2021-10-05"]


def test_closes_on_is_guarded_and_keyed_by_jquants_code() -> None:
    view = _store().view("2021-10-04")

    closes = view.closes_on("2021-10-04")

    assert closes["72030"] == 101.0
    with pytest.raises(ps.FutureDataAccessError):
        view.closes_on("2021-10-05")


async def test_ensure_bar_cache_skips_dates_outside_subscription(tmp_path: Path) -> None:
    """契約プラン範囲外（400 + 範囲本文）の日は取得も記録もせずに飛ばす（空=祝日と誤認しない）."""
    from backend.services.data.jquants_errors import JQuantsClientError

    async def fake_fetch(date: str) -> list[dict[str, object]]:
        if date < "2021-10-04":
            raise JQuantsClientError(
                "/equities/bars/daily",
                400,
                body="Your subscription covers the following dates: 2021-10-04 ~ 2026-09-22",
            )
        return [_bar(date, "72030", 100.0)]

    fetched = await ps.ensure_bar_cache("2021-09-30", "2021-10-05", cache_dir=tmp_path, fetch=fake_fetch)

    assert fetched == 2
    assert sorted(p.name for p in tmp_path.iterdir()) == ["2021-10-04.csv.gz", "2021-10-05.csv.gz"]


async def test_ensure_bar_cache_propagates_other_client_errors(tmp_path: Path) -> None:
    from backend.services.data.jquants_errors import JQuantsClientError

    async def fake_fetch(date: str) -> list[dict[str, object]]:
        raise JQuantsClientError("/equities/bars/daily", 401, body="unauthorized")

    with pytest.raises(JQuantsClientError):
        await ps.ensure_bar_cache("2021-10-04", "2021-10-05", cache_dir=tmp_path, fetch=fake_fetch)
