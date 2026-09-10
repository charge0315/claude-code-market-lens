"""営業日カレンダーユーティリティの検証."""

from __future__ import annotations

import pandas as pd
import pytest

from backend.services.trading_calendar import calc_target_date


def test_calc_target_date_skips_weekend() -> None:
    # 2026-09-11 は金曜。1 営業日先は翌月曜 2026-09-14。
    assert calc_target_date(pd.Timestamp("2026-09-11"), 1) == "2026-09-14"


def test_calc_target_date_multiple_business_days() -> None:
    assert calc_target_date(pd.Timestamp("2026-09-10"), 5) == "2026-09-17"


@pytest.mark.parametrize("horizon", [0, -1])
def test_calc_target_date_rejects_non_positive_horizon(horizon: int) -> None:
    with pytest.raises(ValueError, match="horizon"):
        calc_target_date(pd.Timestamp("2026-09-10"), horizon)
