"""需給分析サービス（週末信用取引残高、J-Quants由来）.

🆕 中長期ピック限定の追加判断材料（ユーザー指示）。ニュース見出しセンチメント
（`llm_news_sentiment_service`）とは異なり、信用取引残高は J-Quants の構造化数値であり
自由記述の本文が無い＝プロンプトインジェクションのリスクが無いため、隔離 LLM 呼び出しは
不要（`fundamental_signals`/`technical_signals` と同じ「構造化シグナルをそのままメイン
プロンプトへ渡す」方式）。

信用倍率（買い残 ÷ 売り残）が高い/低いことの強気・弱気の断定は行わない（factsのみ）。
古典的な信用取引の解釈（買い長残過多＝将来の潜在的売り圧力、売り長残増加＝踏み上げ余地）を
`render_supply_demand_block` の説明文で LLM に伝えるに留め、composite_score への重み付き
統合は v1 では行わない（`plans` 参照、較正・promotion gate への影響を避けるため）。
"""

from __future__ import annotations

import logging

from backend.services.data.jquants_client import jquants
from backend.services.data.jquants_errors import JQuantsError

logger = logging.getLogger(__name__)

# 信用倍率（買い残÷売り残）の分類しきい値（第一版のヒューリスティック、要将来キャリブレーション）。
_LONG_HEAVY_THRESHOLD = 6.0
_SHORT_HEAVY_THRESHOLD = 1.0

_CLASSIFICATION_LABELS: dict[str, str] = {
    "long_heavy": "買い長残優勢",
    "short_heavy": "売り長残優勢",
    "balanced": "均衡",
}


def classify_margin_ratio(margin_ratio: float) -> str:
    """信用倍率から3分類ラベル（long_heavy / short_heavy / balanced）を返す（断定的な方向判定はしない）."""
    if margin_ratio >= _LONG_HEAVY_THRESHOLD:
        return "long_heavy"
    if margin_ratio <= _SHORT_HEAVY_THRESHOLD:
        return "short_heavy"
    return "balanced"


async def get_supply_demand_data(ticker: str) -> dict[str, object] | None:
    """指定銘柄の直近週末信用取引残高を取得し、信用倍率・週次変化を算出する.

    J-Quants 未設定・プラン未対応（403）・データ無し（貸借銘柄でない等）・信用売り残 0 は
    いずれも `None`（フェイルソフト、`ml_prediction` と同じ「材料が無ければ渡さない」方針）。
    """
    if not jquants.is_configured:
        return None

    try:
        records = await jquants.fetch_weekly_margin_interest(ticker)
    except JQuantsError as e:
        logger.info("週末信用取引残高の取得をスキップします（銘柄=%s）: %s", ticker, e)
        return None

    if not records:
        return None

    latest = records[0]
    if latest.long_volume is None or latest.short_volume is None or latest.short_volume == 0:
        return None

    margin_ratio = latest.long_volume / latest.short_volume

    margin_ratio_prev: float | None = None
    short_ratio_change_wow: float | None = None
    if len(records) > 1:
        prev = records[1]
        if prev.long_volume is not None and prev.short_volume:
            margin_ratio_prev = prev.long_volume / prev.short_volume
        if prev.short_volume:
            short_ratio_change_wow = (latest.short_volume - prev.short_volume) / prev.short_volume

    return {
        "as_of": latest.date,
        "long_volume": latest.long_volume,
        "short_volume": latest.short_volume,
        "margin_ratio": round(margin_ratio, 2),
        "margin_ratio_prev": round(margin_ratio_prev, 2) if margin_ratio_prev is not None else None,
        "short_ratio_change_wow": round(short_ratio_change_wow, 4) if short_ratio_change_wow is not None else None,
        "classification": classify_margin_ratio(margin_ratio),
    }


def render_supply_demand_block(data: dict[str, object] | None) -> str | None:
    """`build_pick_prompt` へ渡す提示ブロックを組み立てる（構造化数値のみ、隔離LLM不要）."""
    if data is None:
        return None

    margin_ratio = data["margin_ratio"]
    classification = _CLASSIFICATION_LABELS.get(str(data["classification"]), str(data["classification"]))
    lines = [
        "## 週末信用取引残高（構造化数値のみ・J-Quants由来）",
        f"- 時点: {data['as_of']}",
        f"- 信用買い残: {data['long_volume']:.0f}株 / 信用売り残: {data['short_volume']:.0f}株",
        f"- 信用倍率（買い残÷売り残）: {margin_ratio:.2f}倍（分類: {classification}）",
    ]
    margin_ratio_prev = data.get("margin_ratio_prev")
    if isinstance(margin_ratio_prev, (int, float)):
        lines.append(f"- 前週の信用倍率: {margin_ratio_prev:.2f}倍")
    short_ratio_change_wow = data.get("short_ratio_change_wow")
    if isinstance(short_ratio_change_wow, (int, float)):
        lines.append(f"- 信用売り残の週次増減率: {short_ratio_change_wow * 100:+.1f}%")
    lines.append(
        "（一般的な解釈: 信用倍率が高い＝買い長残が売り長残に比べ多く、将来の利益確定売り等の"
        "潜在的な供給要因になり得る。信用売り残の増加は将来の踏み上げ（買い戻し）余地を示す"
        "こともある。本データは方向性を断定するものではなく、他の材料と合わせて判断すること）"
    )
    return "\n".join(lines)
