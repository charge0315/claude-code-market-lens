"""決算サプライズ・予想修正モメンタム分析サービス（J-Quants由来）.

🆕 需給分析（`supply_demand_analyzer.py`）と同じ「llm_overlayステージの追加判断材料」として
配線する（`orchestrator.py` 参照）。ホライズンによる gate は行わず短期・中長期の両方が対象
（決算サプライズは発表直後の値動きに直結するイベントドリブン材料のため、需給軸のような
中長期限定にはしない）。J-Quants の構造化数値（会社側の当期通期予想フィールド）のみで
自由記述本文が無いため、プロンプトインジェクションのリスクが無く隔離LLM呼び出しも不要
（`fundamental_signals`/`technical_signals` と同じ「構造化シグナルをそのままメインプロンプト
へ渡す」方式）。

**重要な制約**（2026-09-22、`code=72030` で実 API 呼び出し検証済み）: J-Quants
`/fins/summary` は四半期決算短信（`DocType` が `1Q`/`2Q`/`3Q`/`FY` FinancialStatements）のみを
返し、単発の「業績予想の修正に関するお知らせ」（決算発表と無関係なタイミングで出る適時開示）は
このエンドポイントには現れない。そのため本サービスが検出できるのは「四半期決算のたびに更新
される会社側の通期予想の変化」のみ。決算サプライズ（実績 vs 直前予想）は本決算
（`period_type == "FY"`）時点でのみ計算する（1Q〜3Q の累計実績と通期予想は単位が異なり単純
比較できないため）。予想修正モメンタムは同一 `fiscal_year_end` を持つ連続開示があれば任意の
開示で計算するが、FY をまたぐ比較（今期予想 vs 前期に出ていた次期予想 `NxFSales` 等）は v1 では
対象外（次期予想フィールドが別建てのため、将来拡張の余地として残す）。
"""

from __future__ import annotations

import logging

from backend.models.jquants_raw import RawStatement
from backend.services.data.jquants_client import jquants
from backend.services.data.jquants_errors import JQuantsError

logger = logging.getLogger(__name__)

# 予想修正の3分類しきい値（デッドバンド、第一版のヒューリスティック、要将来キャリブレーション）。
_REVISION_DEADBAND = 0.01

_REVISION_LABELS: dict[str, str] = {
    "upward": "上方修正",
    "downward": "下方修正",
    "unchanged": "据え置き",
}

# (実績フィールド名, 通期予想フィールド名, 表示ラベル) の組。
_METRICS: tuple[tuple[str, str, str], ...] = (
    ("net_sales", "forecast_net_sales", "売上高"),
    ("operating_profit", "forecast_operating_profit", "営業利益"),
    ("ordinary_profit", "forecast_ordinary_profit", "経常利益"),
    ("profit", "forecast_profit", "純利益"),
    ("eps", "forecast_eps", "EPS"),
)


def classify_revision(revision_rate: float) -> str:
    """予想修正率から3分類ラベル（upward/downward/unchanged）を返す（断定的な方向判定はしない）."""
    if revision_rate >= _REVISION_DEADBAND:
        return "upward"
    if revision_rate <= -_REVISION_DEADBAND:
        return "downward"
    return "unchanged"


def _rate(actual: float | None, base: float | None) -> float | None:
    if actual is None or base is None or base == 0:
        return None
    return (actual - base) / abs(base)


def _compute_surprise(latest: RawStatement, prior: RawStatement | None) -> dict[str, dict[str, object]] | None:
    """本決算の実績 vs 直前開示の通期予想（同一fiscal_year_end）から決算サプライズを計算する."""
    if latest.period_type != "FY" or prior is None or prior.fiscal_year_end != latest.fiscal_year_end:
        return None

    metrics: dict[str, dict[str, object]] = {}
    for actual_field, forecast_field, label in _METRICS:
        actual = getattr(latest, actual_field)
        prior_forecast = getattr(prior, forecast_field)
        rate = _rate(actual, prior_forecast)
        if rate is not None:
            metrics[actual_field] = {
                "label": label,
                "actual": actual,
                "prior_forecast": prior_forecast,
                "surprise_rate": round(rate, 4),
            }

    return metrics or None


def _compute_revision(latest: RawStatement, prior: RawStatement | None) -> dict[str, dict[str, object]] | None:
    """直近開示の通期予想 vs 直前開示の通期予想（同一fiscal_year_end）から予想修正モメンタムを計算する."""
    if prior is None or prior.fiscal_year_end != latest.fiscal_year_end:
        return None

    metrics: dict[str, dict[str, object]] = {}
    for _actual_field, forecast_field, label in _METRICS:
        current_forecast = getattr(latest, forecast_field)
        prior_forecast = getattr(prior, forecast_field)
        rate = _rate(current_forecast, prior_forecast)
        if rate is not None:
            metrics[forecast_field] = {
                "label": label,
                "current_forecast": current_forecast,
                "prior_forecast": prior_forecast,
                "revision_rate": round(rate, 4),
                "classification": classify_revision(rate),
            }

    return metrics or None


async def get_earnings_surprise_data(ticker: str) -> dict[str, object] | None:
    """指定銘柄の直近決算開示から決算サプライズ・予想修正モメンタムを算出する.

    J-Quants 未設定・上流障害・開示不足（1 件以下）・サプライズ/修正のいずれも算出不能は
    いずれも `None`（フェイルソフト、`supply_demand_analyzer` と同じ「材料が無ければ渡さない」
    方針）。
    """
    if not jquants.is_configured:
        return None

    try:
        records = await jquants.fetch_statements(ticker)
    except JQuantsError as e:
        logger.info("決算データの取得をスキップします（銘柄=%s）: %s", ticker, e)
        return None

    if len(records) < 2:
        return None

    latest, prior = records[0], records[1]
    surprise = _compute_surprise(latest, prior)
    revision = _compute_revision(latest, prior)
    if surprise is None and revision is None:
        return None

    return {
        "as_of": latest.disclosed_date,
        "fiscal_year_end": latest.fiscal_year_end,
        "period_type": latest.period_type,
        "surprise": surprise,
        "revision": revision,
    }


def render_earnings_surprise_block(data: dict[str, object] | None) -> str | None:
    """`build_pick_prompt` へ渡す提示ブロックを組み立てる（構造化数値のみ、隔離LLM不要）."""
    if data is None:
        return None

    lines = [
        "## 決算サプライズ・予想修正モメンタム（構造化数値のみ・J-Quants由来）",
        f"- 直近開示: {data['as_of']}（{data['period_type']}、通期末 {data['fiscal_year_end']}）",
    ]

    surprise = data.get("surprise")
    if isinstance(surprise, dict) and surprise:
        lines.append("- 決算サプライズ（本決算の実績 vs 直前開示時点の自社通期予想）:")
        for metric in surprise.values():
            rate = float(metric["surprise_rate"]) * 100
            lines.append(
                f"  - {metric['label']}: 実績 {metric['actual']:,.1f} / 直前予想 {metric['prior_forecast']:,.1f}"
                f"（乖離 {rate:+.1f}%）"
            )

    revision = data.get("revision")
    if isinstance(revision, dict) and revision:
        lines.append("- 通期予想の修正状況（今回開示 vs 前回開示の自社通期予想）:")
        for metric in revision.values():
            rate = float(metric["revision_rate"]) * 100
            label = _REVISION_LABELS.get(str(metric["classification"]), str(metric["classification"]))
            lines.append(
                f"  - {metric['label']}: {metric['current_forecast']:,.1f}（前回 {metric['prior_forecast']:,.1f}、"
                f"修正 {rate:+.1f}%、{label}）"
            )

    lines.append(
        "（一般的な解釈: 決算サプライズは自社予想に対する上振れ/下振れであり市場コンセンサスとの"
        "比較ではない点に注意。通期予想の修正は四半期決算のたびに更新される会社側の自己申告"
        "ベースであり、単発の業績予想修正リリースは含まない。本データは方向性を断定するものでは"
        "なく、他の材料と合わせて判断すること）"
    )
    return "\n".join(lines)
