"""銘柄別モデル学習用の株価データ取得（🆕 P14、J-Quants フォールバック）.

`per_ticker_training_service` の学習データ取得は、これまで yfinance
（`data_fetcher.get_stock_data`）一本だった。新形式コード（例: "166A"）や小型株では
yfinance の履歴が薄い/欠損していることがあり、`feature_engineering.build_feature_matrix`
の最低履歴日数チェックに引っかかって学習が失敗するケースが実機で確認された
（`plans/04_タスクリスト.md` P14）。

J-Quants（`jquants_client.fetch_daily_quotes`）は東証の公式データソースであり、
yfinance 互換の DataFrame（Date インデックス、Open/High/Low/Close/Volume 列）を
既に返す設計のため、yfinance が不十分な場合のフォールバック source として使う。
学習用途のためフェイルソフトが必須（J-Quants 側の障害で学習全体を止めない）。
"""

from __future__ import annotations

import asyncio
import logging

import pandas as pd

from backend.services.data.data_fetcher import get_stock_data
from backend.services.data.jquants_client import jquants
from backend.services.data.jquants_errors import JQuantsError
from backend.services.learning.feature_engineering import MIN_HISTORY_DAYS

logger = logging.getLogger(__name__)


async def fetch_training_ohlcv(ticker: str, period: str) -> pd.DataFrame:
    """学習用 OHLCV を取得する（yfinance 優先、不足時は J-Quants にフォールバック）.

    yfinance の結果が `MIN_HISTORY_DAYS` 以上あればそのまま返す（フォールバック不要、
    既存の挙動を変えない）。不足・空で `JQUANTS_API_KEY` が設定済みなら J-Quants を
    試し、より行数の多い方を採用する。J-Quants 側が失敗しても yfinance の結果
    （不足していてもそのまま）を返し、呼び出し元の既存エラーハンドリングに委ねる。
    """
    yf_df = await asyncio.to_thread(get_stock_data, ticker, period=period)
    if len(yf_df) >= MIN_HISTORY_DAYS or not jquants.is_configured:
        return yf_df

    try:
        jq_df = await jquants.fetch_daily_quotes(ticker, period=period)
    except JQuantsError as e:
        logger.warning("J-Quants 学習データフォールバックに失敗しました（%s）: %s", ticker, e)
        return yf_df

    return jq_df if len(jq_df) > len(yf_df) else yf_df
