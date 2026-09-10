"""JST（日本標準時）関連の共通ヘルパー.

Market Lens `backend/services/jst_time.py` から移植（変更なし）。
`today_jst` / `week_jst` は日次・週次機能の冪等キー生成に、`to_jst` / `is_today_jst` は
yfinance の tz 付きタイムスタンプ処理に、`merge_equity_curves` はピック累積成績の
エクイティカーブ合算（P4）に使う。
"""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

import pandas as pd

JST = ZoneInfo("Asia/Tokyo")


def today_jst() -> str:
    """JST 基準の本日日付を YYYY-MM-DD 形式で返す（サーバのローカル TZ に依存しない）."""
    return datetime.now(JST).date().isoformat()


def week_jst() -> str:
    """JST 基準の本日が属する ISO 週を YYYY-Www 形式で返す（週次機能の冪等キー用）."""
    iso = datetime.now(JST).date().isocalendar()
    return f"{iso.year}-W{iso.week:02d}"


def to_jst(ts: pd.Timestamp) -> pd.Timestamp:
    """タイムスタンプを JST に変換する（tz-naive の場合は JST としてローカライズする）."""
    if ts.tzinfo is None:
        return ts.tz_localize(JST)
    return ts.tz_convert(JST)


def is_today_jst(ts: pd.Timestamp) -> bool:
    """タイムスタンプの日付が JST 基準の本日と一致するかを返す."""
    return to_jst(ts).date() == datetime.now(JST).date()


def merge_equity_curves(per_ticker: dict[str, pd.Series]) -> pd.Series:
    """複数銘柄のエクイティ系列を 1 本の共通タイムラインに合算する.

    タイムスタンプの和集合に揃え、各銘柄の欠損点は ffill（他銘柄のみ動いた時刻の直前値を維持）
    + bfill（先頭欠損を自身の初期値で埋める）で補完してから合算する。
    """
    if not per_ticker:
        return pd.Series(dtype=float)
    combined_index = sorted(set().union(*(s.index for s in per_ticker.values())))
    aligned = [s.reindex(combined_index).ffill().bfill() for s in per_ticker.values()]
    total = aligned[0]
    for s in aligned[1:]:
        total = total.add(s, fill_value=0.0)
    return total
