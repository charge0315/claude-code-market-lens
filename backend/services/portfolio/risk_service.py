"""ポートフォリオのリスクチェック（セクター集中度・銘柄間相関）.

Market Lens `backend/services/risk_service.py` から移植（⭐、`ticker`→`symbol` 改称のみ）。
プロのポートフォリオマネージャーは、個別銘柄の評価が良くても「相関の高い銘柄ばかり
保有している」「特定セクターに偏っている」状態を実質的な分散不足とみなす。
`portfolio_service.build_portfolio()` が読み書きするデータを読み取るだけの警告専用レイヤーで、
新規テーブルは持たずリクエストの都度計算する（保有銘柄の更新頻度自体が低いため）。

Market Lens の AI 銘柄ピック向けバリアント（`analyze_stock_pick_risk`）は対象外
（`stock_pick_runs` JSON blob 前提で Alpha Forge の `prediction_ledger` とは形が異なる）。
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Sequence
from datetime import datetime
from itertools import combinations

import pandas as pd

from backend.models.risk import CorrelationWarning, PortfolioRiskReport, SectorConcentrationWarning
from backend.services.data import data_fetcher
from backend.services.jst_time import JST
from backend.services.portfolio.portfolio_service import build_portfolio

logger = logging.getLogger(__name__)

# セクター集中度警告の閾値（保有評価額全体に対する比率）。
# 単一セクターへの配分が30〜40%を超えると分散効果が薄れ始めるとされる一般的な目安を踏まえ、
# 常時警告が出て意味を失わない程度にやや緩めの40%を採用する。
_SECTOR_CONCENTRATION_THRESHOLD_PCT = 40.0

# 値動きが似ている（分散効果が薄い）とみなす相関係数の閾値（統計的な「強い正の相関」の目安）。
_CORRELATION_WARNING_THRESHOLD = 0.7

# 相関計算に使う価格系列の対象期間（ピックの ATR 算出と同じ3ヶ月）。
_CORRELATION_LOOKBACK_PERIOD = "3mo"

# ペアワイズ相関を計算するために最低限必要な銘柄数（1銘柄ではペアが作れない）
_MIN_SYMBOLS_FOR_CORRELATION = 2


async def analyze_portfolio_risk() -> PortfolioRiskReport:
    """現在の保有銘柄に対し、セクター集中度と銘柄間相関の警告を計算する.

    `build_portfolio()` が既に算出した現在価格・セクター別配分比率をそのまま利用し、
    yfinance 呼び出しロジックの重複を避ける（DRY）。
    """
    summary = await build_portfolio()

    sector_warnings = [_to_sector_warning(alloc.sector, alloc.pct) for alloc in summary.sector_allocations]

    symbols_info = [(h.symbol, h.company_name) for h in summary.holdings]
    correlation_warnings, correlation_skipped = await _compute_correlation_warnings(symbols_info)

    return PortfolioRiskReport(
        analyzed_count=len(summary.holdings),
        sector_warnings=sector_warnings,
        correlation_warnings=correlation_warnings,
        correlation_skipped=correlation_skipped,
        message="保有銘柄がありません" if not summary.holdings else None,
        generated_at=_now_iso(),
    )


# ---------------------------------------------------------------------------
# セクター集中度
# ---------------------------------------------------------------------------


def _to_sector_warning(sector: str, pct: float) -> SectorConcentrationWarning:
    exceeds = pct >= _SECTOR_CONCENTRATION_THRESHOLD_PCT
    return SectorConcentrationWarning(sector=sector, pct=pct, exceeds_threshold=exceeds)


async def fetch_sector(symbol: str) -> str | None:
    """1銘柄のセクター情報を取得する（取得失敗時は None を返し「その他」に分類させる）.

    1銘柄の失敗が分析全体を止めないよう、該当銘柄だけスキップしてログを残す耐障害性パターン。
    """
    try:
        info = await asyncio.to_thread(data_fetcher.get_company_info, symbol)
        return info.get("sector") if info else None
    except Exception:
        logger.warning("リスクチェック: セクター情報取得に失敗しました: %s", symbol, exc_info=True)
        return None


# ---------------------------------------------------------------------------
# 銘柄間相関
# ---------------------------------------------------------------------------


async def _compute_correlation_warnings(
    symbols_info: Sequence[tuple[str, str | None]],
) -> tuple[list[CorrelationWarning], bool]:
    """各銘柄の直近リターン系列からペアワイズ相関を計算し、閾値超えのペアを警告として返す.

    戻り値の bool は「相関計算自体をスキップしたか」を表す
    （2銘柄未満、または価格取得に成功した銘柄が2未満の場合）。
    """
    if len(symbols_info) < _MIN_SYMBOLS_FOR_CORRELATION:
        return [], True

    series_list = await asyncio.gather(*[_safe_fetch_returns(symbol) for symbol, _name in symbols_info])
    returns: dict[str, pd.Series] = {}
    names: dict[str, str | None] = {}
    for (symbol, company_name), series in zip(symbols_info, series_list, strict=True):
        if series is not None:
            returns[symbol] = series
            names[symbol] = company_name

    if len(returns) < _MIN_SYMBOLS_FOR_CORRELATION:
        return [], True

    # 日付インデックスは pandas が自動的に和集合を取り、欠損日は NaN として扱われる。
    # corr() はデフォルトでペアごとに欠損値を除外して計算するため、銘柄ごとの
    # データ取得期間のわずかなずれ（新規上場・取引停止等）があっても計算は成立する。
    corr_matrix = pd.DataFrame(returns).corr()

    warnings: list[CorrelationWarning] = []
    for symbol_a, symbol_b in combinations(corr_matrix.columns, 2):
        corr = corr_matrix.loc[symbol_a, symbol_b]
        if pd.notna(corr) and corr >= _CORRELATION_WARNING_THRESHOLD:
            warnings.append(
                CorrelationWarning(
                    symbol_a=symbol_a,
                    symbol_b=symbol_b,
                    company_name_a=names.get(symbol_a),
                    company_name_b=names.get(symbol_b),
                    correlation=float(corr),
                )
            )

    return warnings, False


async def _safe_fetch_returns(symbol: str) -> pd.Series | None:
    """1銘柄の直近終値からリターン系列を取得する（取得失敗・データ不足時は None でこの銘柄だけスキップ）."""
    try:
        df = await asyncio.to_thread(data_fetcher.get_stock_data, symbol, _CORRELATION_LOOKBACK_PERIOD)
        if df.empty or "Close" not in df.columns or len(df) < 2:
            return None
        return df["Close"].pct_change().dropna()
    except Exception:
        logger.warning("リスクチェック: 価格データ取得に失敗しました: %s", symbol, exc_info=True)
        return None


def _now_iso() -> str:
    """JST 基準の現在時刻を ISO 8601 形式で返す."""
    return datetime.now(JST).isoformat()
