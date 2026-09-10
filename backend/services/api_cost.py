"""Claude API 呼び出しのトークン使用量から推定コスト (USD) を算出し記録する.

Market Lens `backend/services/api_cost.py` から移植。変更点:
- DB アクセスを raw sqlite `database` → SQLAlchemy async `services/db/api_cost_db` に置換。

`anthropic_client` が `messages.create` のレスポンスを受け取った直後に `record_usage()` を
呼び、`api_costs` に 1 行 upsert する。**記録は完全にベストエフォート**で、失敗しても
本来の LLM 呼び出し結果には影響させない（例外を外へ伝播させない）。

価格は 100 万トークンあたりの USD（2026-01 時点の公開価格ベースの概算）。価格表に無い
モデル（例: claude-fable-5）は Sonnet 相当で概算し `pricing_known=False` で記録する。
"""

from __future__ import annotations

import logging
from datetime import date, timedelta

from backend.models.api_cost import ApiCostDailyRow, ApiCostSummary
from backend.services.db import api_cost_db
from backend.services.jst_time import today_jst

logger = logging.getLogger(__name__)


class ModelPricing:
    """1 モデル分の 100 万トークンあたり単価 (USD)."""

    __slots__ = ("input", "output")

    def __init__(self, *, input_: float, output: float) -> None:
        self.input = input_
        self.output = output


# キーはモデル ID の前方一致で照合する（より具体的なプレフィクスを先に並べる）。
_PRICING: dict[str, ModelPricing] = {
    "claude-opus": ModelPricing(input_=15.0, output=75.0),
    "claude-sonnet": ModelPricing(input_=3.0, output=15.0),
    "claude-3-5-haiku": ModelPricing(input_=1.0, output=5.0),
    "claude-3-haiku": ModelPricing(input_=0.25, output=1.25),
    "claude-haiku": ModelPricing(input_=1.0, output=5.0),
}

# 価格表に無いモデル（例: claude-fable-5）の概算。Sonnet 相当を上限側の目安に置く。
_FALLBACK_PRICING = ModelPricing(input_=3.0, output=15.0)

_CACHE_READ_MULTIPLIER = 0.1
_CACHE_WRITE_MULTIPLIER = 1.25
_PER_MILLION = 1_000_000.0


def _resolve_pricing(model: str) -> tuple[ModelPricing, bool]:
    """モデル ID に対応する単価と「価格表に存在したか」を返す."""
    normalized = model.strip().lower()
    for prefix, pricing in _PRICING.items():
        if normalized.startswith(prefix):
            return pricing, True
    return _FALLBACK_PRICING, False


def estimate_cost(
    model: str,
    *,
    input_tokens: int,
    output_tokens: int,
    cache_read_tokens: int = 0,
    cache_write_tokens: int = 0,
) -> tuple[float, bool]:
    """トークン使用量から推定コスト (USD) を計算する。返り値は (推定 USD, 価格表に存在したか)."""
    pricing, known = _resolve_pricing(model)
    cost = (
        input_tokens * pricing.input
        + output_tokens * pricing.output
        + cache_read_tokens * pricing.input * _CACHE_READ_MULTIPLIER
        + cache_write_tokens * pricing.input * _CACHE_WRITE_MULTIPLIER
    ) / _PER_MILLION
    return cost, known


def _int_attr(obj: object, name: str) -> int:
    """usage オブジェクトから int 属性を安全に取り出す（無ければ / None なら 0）."""
    value = getattr(obj, name, None)
    if isinstance(value, bool):  # bool は int のサブクラスなので明示的に弾く
        return 0
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    return 0


async def record_usage(*, feature: str, model: str, usage: object) -> None:
    """LLM レスポンスの usage から推定コストを算出し api_costs に 1 行 upsert する（ベストエフォート）."""
    if usage is None:
        return
    try:
        input_tokens = _int_attr(usage, "input_tokens")
        output_tokens = _int_attr(usage, "output_tokens")
        cache_read_tokens = _int_attr(usage, "cache_read_input_tokens")
        cache_write_tokens = _int_attr(usage, "cache_creation_input_tokens")

        cost, known = estimate_cost(
            model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cache_read_tokens=cache_read_tokens,
            cache_write_tokens=cache_write_tokens,
        )

        await api_cost_db.insert_api_cost_log(
            log_date=today_jst(),
            feature=feature,
            model=model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cache_read_tokens=cache_read_tokens,
            cache_write_tokens=cache_write_tokens,
            est_cost_usd=cost,
            pricing_known=known,
        )
    except Exception:  # noqa: BLE001 — コスト記録は本処理をブロックしない
        logger.warning("API コスト記録に失敗しました (feature=%s model=%s)", feature, model, exc_info=True)


def _row_float(value: object) -> float:
    return float(value) if isinstance(value, (int, float)) else 0.0


def _row_int(value: object) -> int:
    return int(value) if isinstance(value, (int, float)) else 0


def _row_str(value: object) -> str:
    return str(value) if value is not None else ""


async def build_api_cost_summary(days: int = 30) -> ApiCostSummary:
    """直近 days 日分の Claude API コストを日付 × 機能で集計して返す."""
    since = (date.fromisoformat(today_jst()) - timedelta(days=max(days - 1, 0))).isoformat()
    raw_rows = await api_cost_db.get_api_cost_rows_since(since)

    rows: list[ApiCostDailyRow] = []
    by_feature: dict[str, float] = {}
    total_cost = 0.0
    total_calls = 0
    for r in raw_rows:
        cost = _row_float(r["est_cost_usd"])
        calls = _row_int(r["call_count"])
        feature = _row_str(r["feature"])
        rows.append(
            ApiCostDailyRow(
                log_date=_row_str(r["log_date"]),
                feature=feature,
                call_count=calls,
                input_tokens=_row_int(r["input_tokens"]),
                output_tokens=_row_int(r["output_tokens"]),
                est_cost_usd=round(cost, 6),
            )
        )
        by_feature[feature] = round(by_feature.get(feature, 0.0) + cost, 6)
        total_cost += cost
        total_calls += calls

    return ApiCostSummary(
        since_date=since,
        total_cost_usd=round(total_cost, 6),
        total_calls=total_calls,
        by_feature=by_feature,
        rows=rows,
    )
