"""予測対象日（target_date）算出用の営業日カレンダーユーティリティ.

Market Lens `backend/services/trading_calendar.py` から移植（変更なし）。
Predictor レイヤは「何営業日先を予測するか」という horizon のみを扱い、実日付には
関知しない設計のため、最終データ日 → 実日付の変換をここへ集約する。

Note: `pandas.tseries.offsets.BDay` は土日のみを非営業日として扱う。日本市場固有の
祝日（年末年始・GW 等）は考慮しないため、祝日を挟む場合は前倒しの日付になり得る
（`calc_target_date` 自体は未対応のまま — 継続学習の決着記録側で必要になった時点で対応する）。
`is_trading_day_jst`/`is_market_hours_jst`（現在時刻の営業日判定）は 🆕 `jpholiday` 導入により
祝日込みで判定する（2026-09-21〜23 の3連休で `is_weekday_jst` だけでは休場日と判定できず
`run_picks_task` 等が誤発火した事故を受けて追加）。
"""

from __future__ import annotations

from datetime import datetime, time
from typing import Literal

import jpholiday
import pandas as pd
from pandas.tseries.offsets import BDay

from backend.services.jst_time import JST

# 東証の立会時間（大引け 15:00、監視は 15:30 まで）。
# `tasks._is_market_hours_jst` と同じ定数・判定ロジック（🆕 P13、市況ステータス表示用に
# 公開関数として追加。`tasks.py` 側は既存テストが `tasks.datetime` の凍結に依存しているため
# 独立実装のまま残し、こちらは新規のマーケットスナップショット機能専用に使う）。
_MARKET_OPEN_JST = time(9, 0)
_MARKET_CLOSE_JST = time(15, 30)


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


def is_weekday_jst() -> bool:
    """現在の曜日が JST 基準で平日かを判定する（祝日は含まない — 休場日判定は `is_trading_day_jst`）."""
    return datetime.now(JST).weekday() < 5  # 5=土, 6=日


def is_trading_day_jst() -> bool:
    """現在日が JST 基準で東証の営業日（平日かつ祝日でない）かを判定する（🆕 jpholiday 導入）."""
    return is_weekday_jst() and not jpholiday.is_holiday(datetime.now(JST).date())


def is_market_hours_jst() -> bool:
    """現在時刻が JST 基準の営業日・東証立会時間内かを判定する."""
    if not is_trading_day_jst():
        return False
    return _MARKET_OPEN_JST <= datetime.now(JST).time() <= _MARKET_CLOSE_JST


def market_status_label() -> Literal["寄り前", "ザラ場中", "引け後"]:
    """現在時刻から市況ステータスの表示ラベルを返す（🆕 P13、ダッシュボードの市況バッジ用）."""
    if not is_trading_day_jst():
        return "引け後"
    now = datetime.now(JST).time()
    if now < _MARKET_OPEN_JST:
        return "寄り前"
    if now > _MARKET_CLOSE_JST:
        return "引け後"
    return "ザラ場中"
