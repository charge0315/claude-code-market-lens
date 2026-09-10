"""予測対象日（target_date）算出用の営業日カレンダーユーティリティ.

Market Lens `backend/services/trading_calendar.py` から移植（変更なし）。
Predictor レイヤは「何営業日先を予測するか」という horizon のみを扱い、実日付には
関知しない設計のため、最終データ日 → 実日付の変換をここへ集約する。

Note: `pandas.tseries.offsets.BDay` は土日のみを非営業日として扱う。日本市場固有の
祝日（年末年始・GW 等）は考慮しないため、祝日を挟む場合は前倒しの日付になり得る。
祝日考慮の精緻化は継続学習の決着記録（P4）で必要になった時点で jpholiday 等を検討する。
"""

from __future__ import annotations

import pandas as pd
from pandas.tseries.offsets import BDay


def calc_target_date(last_date: pd.Timestamp, horizon: int) -> str:
    """直近データ日から horizon 営業日後の日付を YYYY-MM-DD 形式で返す.

    Args:
        last_date: 予測に用いた株価データの最終日付
        horizon: 何営業日先を予測対象とするか（1 以上）

    Raises:
        ValueError: horizon が 1 未満の場合
    """
    if horizon < 1:
        raise ValueError(f"horizon は 1 以上である必要があります（horizon={horizon}）")
    return (last_date + BDay(horizon)).strftime("%Y-%m-%d")
