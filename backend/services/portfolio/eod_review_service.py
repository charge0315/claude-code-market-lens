"""大引け後レビュー（EOD Review）— `portfolio_signals` の結果照合と学習教訓の生成（🆕 P7d）.

Market Lens `ai_portfolio_eod.py` の「1) 定量突合 → 2) 介入分析 → 3) LLM で教訓抽出」という
構造のみ参考にした。Market Lens は自前の発注チケット（`order_tickets`、指値・約定シミュレーション
込み）を突合するが、Alpha Forge には無い（アプリはブローカー発注をしない）。代わりに
`portfolio_signals` の当日分を評価件数・状態（proposed/approved/rejected/executed）・
action 内訳で集計するだけの軽量な定量集計にした。`run_date` PK のため 1 日 1 件
（`force=True` で再生成）。

Market Lens は LLM 呼び出し失敗（`AnthropicError`）を永続化せず呼び出し元へ伝播させ、手動
リトライを前提にする設計だが、この関数は celery-beat（16:31 JST 日次）からの無人実行が主経路
のため、伝播させると失敗がログに残るだけで誰もリトライしない。そのため失敗時は定量集計のみの
フォールバック summary で握りつぶし、必ず 1 件は保存する設計にした（`signal_service` が
`LLMError` を握りつぶす方針と同じ）。
"""

from __future__ import annotations

import json
import logging
from collections import Counter
from collections.abc import Mapping, Sequence
from datetime import datetime

from backend.models.eod_review import EodReview, HeuristicItem
from backend.services.db.eod_review_db import get_eod_review, list_recent_eod_reviews, upsert_eod_review
from backend.services.db.portfolio_signal_db import list_signals_for_date
from backend.services.jst_time import JST, today_jst
from backend.services.llm.errors import LLMError
from backend.services.llm.registry import resolve_feature_provider

logger = logging.getLogger(__name__)

_HEURISTIC_LIMIT = 5

# Anthropic 未設定時に返す一般的な教訓（定量集計は実データで行い、教訓だけ定型）。
_MOCK_HEURISTICS: tuple[dict[str, object], ...] = (
    {
        "heuristic": "損切り判定（stop_loss）は却下せず早めに承認する方が、後の含み損拡大を防ぎやすい",
        "evidence": "APIキー未設定のため定量集計のみ（一般的な保守ルール）",
        "confidence": 0.4,
    },
)


def _reconcile(signals: Sequence[Mapping[str, object]]) -> dict[str, object]:
    """`portfolio_signals` 当日分を状態別・action 別に集計する（LLM プロンプトの中間値）."""
    return {
        "evaluated_count": len(signals),
        "status_counts": dict(Counter(str(s["status"]) for s in signals)),
        "action_counts": dict(Counter(str(s["action"]) for s in signals)),
    }


def _build_prompt(run_date: str, stats: dict[str, object], signals: Sequence[Mapping[str, object]]) -> str:
    lines = [
        f"- {s['symbol']} {s['action']}（状態: {s['status']}, 確信度: {s['confidence']}）: {s['rationale']}"
        for s in signals
    ]
    return (
        "あなたはポートフォリオ判定（Human-in-the-Loop）の大引け後アナリストです。"
        "本日 AI が提案した売買タイミング判定と、人間による承認・却下・実約定の結果を踏まえ、"
        "翌営業日以降の判定精度を上げるための具体的な教訓を submit_eod_review で提出してください。\n\n"
        f"## {run_date} の判定集計\n{json.dumps(stats, ensure_ascii=False, indent=2)}\n\n"
        f"## 判定明細（{len(signals)}件）\n" + ("\n".join(lines) or "（なし）")
    )


def _coerce_heuristics(raw: object) -> list[HeuristicItem]:
    items: list[HeuristicItem] = []
    if not isinstance(raw, list):
        return items
    for entry in raw:
        if not isinstance(entry, Mapping):
            continue
        text = str(entry.get("heuristic", "")).strip()
        if not text:
            continue
        try:
            confidence = max(0.0, min(1.0, float(entry.get("confidence", 0.5))))
        except (TypeError, ValueError):
            confidence = 0.5
        items.append(
            HeuristicItem(heuristic=text, evidence=str(entry.get("evidence", "")).strip(), confidence=confidence)
        )
    return items[:_HEURISTIC_LIMIT]


async def _generate(
    run_date: str, stats: dict[str, object], signals: Sequence[Mapping[str, object]]
) -> tuple[str, list[HeuristicItem]]:
    if not signals:
        return "本日は判定がありませんでした。", []
    provider = resolve_feature_provider("eod_review")
    if not provider.is_configured:
        message = (
            f"{provider.provider_id} APIキーが未設定のため、"
            f"定量集計のみ実施しました（{stats['evaluated_count']}件判定）。"
        )
        return message, _coerce_heuristics(list(_MOCK_HEURISTICS))
    try:
        raw = await provider.propose_eod_review(prompt=_build_prompt(run_date, stats, signals))
    except LLMError as e:
        logger.warning("EOD レビューの LLM 呼び出しに失敗: %s", e)
        return f"LLM 呼び出しに失敗したため、定量集計のみ実施しました（{stats['evaluated_count']}件判定）。", []
    summary = str(raw.get("summary", "")).strip() or "（要約なし）"
    return summary, _coerce_heuristics(raw.get("heuristics"))


def _review_from_row(row: Mapping[str, object]) -> EodReview:
    return EodReview(
        review_date=str(row["review_date"]),
        created_at=str(row["created_at"]),
        summary=str(row["summary"]),
        learned_heuristics=[HeuristicItem.model_validate(h) for h in json.loads(str(row["learned_heuristics"]))],
    )


async def get_latest() -> EodReview | None:
    """最も新しい `review_date` のレビューを返す（1 件も無ければ None）."""
    rows = await list_recent_eod_reviews(limit=1)
    return _review_from_row(rows[0]) if rows else None


async def run_eod_review(run_date: str | None = None, *, force: bool = False) -> EodReview:
    """当日の大引け後レビューを実行（初回）または取得（それ以外）する."""
    run_date = run_date or today_jst()

    existing = await get_eod_review(run_date)
    if existing is not None and not force:
        return _review_from_row(existing)

    signals = await list_signals_for_date(run_date)
    stats = _reconcile(signals)
    summary, heuristics = await _generate(run_date, stats, signals)

    created_at = datetime.now(JST).isoformat(timespec="seconds")
    await upsert_eod_review(
        review_date=run_date,
        summary=summary,
        learned_heuristics=[h.model_dump() for h in heuristics],
        created_at=created_at,
    )
    return EodReview(review_date=run_date, created_at=created_at, summary=summary, learned_heuristics=heuristics)
