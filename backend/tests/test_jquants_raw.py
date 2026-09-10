"""J-Quants 生スキーマの検証（alias 束縛・数値強制・前方互換）."""

from __future__ import annotations

from backend.models.jquants_raw import RawDailyBar, RawListedInfo, RawStatement, coerce_optional_float


def test_coerce_optional_float_handles_strings_and_blanks() -> None:
    assert coerce_optional_float("123.5") == 123.5
    assert coerce_optional_float("") is None
    assert coerce_optional_float(None) is None
    assert coerce_optional_float("N/A") is None
    assert coerce_optional_float(10) == 10.0


def test_raw_daily_bar_binds_v2_aliases_and_ignores_extra() -> None:
    bar = RawDailyBar.model_validate(
        {"Date": "2026-09-10", "AdjO": "100", "AdjC": "110.5", "AdjVo": "1000", "UnknownNew": 1}
    )
    assert bar.date == "2026-09-10"
    assert bar.adj_open == 100.0
    assert bar.adj_close == 110.5
    assert bar.adj_volume == 1000.0
    assert bar.adj_high is None  # 欠落は None


def test_raw_statement_alias_and_sort_key_field() -> None:
    st = RawStatement.model_validate({"DiscDate": "2026-08-01", "Sales": "5000", "EPS": "12.3"})
    assert st.disclosed_date == "2026-08-01"
    assert st.net_sales == 5000.0
    assert st.eps == 12.3


def test_raw_listed_info_binds_abbreviated_names() -> None:
    info = RawListedInfo.model_validate({"Code": "72030", "CoName": "トヨタ自動車", "S33Nm": "輸送用機器"})
    assert info.code == "72030"
    assert info.company_name == "トヨタ自動車"
    assert info.sector33_name == "輸送用機器"
