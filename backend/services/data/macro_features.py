"""マクロ市場指標（日経平均・USD/JPY・VIX）を予測モデルの補助特徴量として提供するサービス.

Market Lens `backend/services/macro_features.py` から移植（import パスのみ変更）。

株価ニュースのセンチメントは「現在時点」のスナップショットしか取れず train-serving skew を
起こすが、マクロ指標は yfinance から日次の完全な過去履歴を取得でき、学習時・推論時で同じ
取得ロジックを使えるため時系列特徴量として一貫性がある。対象銘柄（日本株）と指標は取引
カレンダーが異なるため reindex + ffill で整列させてから日次リターンを算出する。

日経VI は yfinance 制約により CBOE VIX（`^VIX`）を代替使用（Market Lens / CLAUDE.md 踏襲）。
"""

from __future__ import annotations

import logging
import math

import pandas as pd

from backend.services.data.data_fetcher import fetch_macro_symbol_data

logger = logging.getLogger(__name__)

_MACRO_PERIOD_BUFFER_YEARS = 1
_DEFAULT_MACRO_PERIOD = "5y"

# yfinance シンボル → 生成する特徴量列名。
# ^N225: 日経平均（国内市場全体のトレンド）/ JPY=X: ドル円（為替影響）/ ^VIX: 日経VI 代替。
_MACRO_SYMBOLS: dict[str, str] = {
    "^N225": "n225_return",
    "JPY=X": "usdjpy_return",
    "^VIX": "vix_return",
}


def derive_macro_period(df: pd.DataFrame) -> str:
    """対象銘柄 DataFrame の日付レンジから、マクロ指標を取得すべき期間を導出する.

    train / predict 時点では元の period 文字列が失われている（df しか渡らない）ため、df の
    実際の日付レンジから逆算する。市場間の休日差を吸収するバッファを足す。
    """
    if not isinstance(df.index, pd.DatetimeIndex) or len(df.index) == 0:
        return _DEFAULT_MACRO_PERIOD

    span_days = (df.index.max() - df.index.min()).days
    years = max(1, math.ceil(span_days / 365) + _MACRO_PERIOD_BUFFER_YEARS)
    return f"{years}y"


def fetch_macro_features(index: pd.DatetimeIndex, period: str = "5y") -> pd.DataFrame:
    """対象銘柄の取引日インデックスに整列したマクロ指標の日次リターンを返す.

    各指標は独立して取得・整列するため、1 指標の取得失敗が他指標や呼び出し元全体を
    巻き込まない（`_fetch_single_return` がフォールバックを内包する）。
    """
    result = pd.DataFrame(index=index)
    for symbol, column_name in _MACRO_SYMBOLS.items():
        result[column_name] = _fetch_single_return(symbol, index, period)
    return result


def _fetch_single_return(symbol: str, index: pd.DatetimeIndex, period: str) -> pd.Series:
    """1 つのマクロ指標を取得し、対象カレンダーに整列した日次リターンを返す.

    取得失敗やデータ欠如時は学習 / 推論パイプライン全体を止めないよう警告ログを出して
    中立値（全行 0.0）にフォールバックする。
    """
    try:
        raw = fetch_macro_symbol_data(symbol, period=period, interval="1d")
        if raw.empty or "Close" not in raw.columns:
            raise ValueError(f"{symbol} の取得結果が空、または Close 列が存在しません")

        aligned = raw["Close"].reindex(index, method="ffill")
        return aligned.pct_change().fillna(0.0)
    except Exception:
        logger.warning("マクロ指標の取得に失敗したため 0 埋めにフォールバックします: %s", symbol, exc_info=True)
        return pd.Series(0.0, index=index)
