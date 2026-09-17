"""日次noteドラフトの生成（🆕）.

本日の公式ピック（中長期・短期）から、entry/stop/target を一切含めない安全な素材のみを
LLM へ渡し、有料note記事の下書き（タイトル・本文）を生成する。具体的な売買価格や断定的な
投資指示は `NOTE_SCHEMA`（`services/llm/schemas.py`）のプロンプトレベルで禁止しているが、
LLM の出力を完全には制御できないため、生成後に軽量な価格表現チェックを行い、該当すれば
`has_price_mention_warning=True` を立てて人間のレビューで気づけるようにする（ブロックはしない
— 最終判断は承認ステップに委ねる、CLAUDE.md の承認制パターン）。
"""

from __future__ import annotations

import re

from backend.models.pick import PickSummary
from backend.services.llm.errors import LLMError
from backend.services.llm.registry import resolve_feature_provider

DISCLAIMER = (
    "\n\n---\n\n"
    "※本記事はAIによる market データの分析結果を紹介する情報提供コンテンツであり、"
    "投資助言ではありません。具体的な売買の判断・タイミングはご自身の責任で行ってください。"
)

# 価格表現の混入チェック（ブロックはしない、レビュー時の注意喚起のみ）。
_PRICE_PATTERN = re.compile(r"[¥￥]\s?\d|\d+\s?円")

_DIRECTION_LABELS: dict[str, str] = {"bullish": "強気", "bearish": "弱気", "neutral": "中立"}


def _pick_lines(picks: list[PickSummary]) -> list[str]:
    """entry/stop/target を含めない安全な要約行を作る（LLMプロンプト素材）."""
    lines: list[str] = []
    for p in picks:
        name = f"（{p.company_name}）" if p.company_name else ""
        direction = _DIRECTION_LABELS.get(p.direction, p.direction)
        tags = "、".join(p.reasoning_tags) if p.reasoning_tags else "特になし"
        lines.append(
            f"- {p.symbol}{name}: 方向性={direction}, 合成スコア={p.composite_score:.1f}, "
            f"確度={p.confidence:.0f}（{p.confidence_bucket}）, 着眼点={tags}\n"
            f"  分析コメント: {p.rationale_text}"
        )
    return lines


def build_prompt(note_date: str, mid_term: list[PickSummary], short_term: list[PickSummary]) -> str:
    """note下書き生成用プロンプトを組み立てる（entry/stop/targetは一切渡さない）."""
    mid_lines = "\n".join(_pick_lines(mid_term)) or "（本日は該当なし）"
    short_lines = "\n".join(_pick_lines(short_term)) or "（本日は該当なし）"
    return (
        "あなたは日本株AI分析noteの執筆者です。以下は本日のAI銘柄ピック（中長期・短期）の"
        "分析結果です。具体的な買値・損切値・売値等の価格や、「買い時」「売るべき」等の"
        "断定的な投資指示は一切書かず、テクニカル・ファンダメンタル・センチメント分析の解説と"
        "一般的な考察のみで、読者が楽しめる記事に仕上げてください。\n\n"
        f"## {note_date} 中長期ピック分析\n{mid_lines}\n\n"
        f"## {note_date} 短期ピック分析\n{short_lines}\n\n"
        "submit_daily_note で記事タイトルと本文（Markdown）を提出してください。"
    )


def has_price_mention(body_markdown: str) -> bool:
    """本文に価格らしき表現が含まれるかを判定する（レビュー時の注意喚起用、ブロックはしない）."""
    return bool(_PRICE_PATTERN.search(body_markdown))


async def generate(note_date: str, mid_term: list[PickSummary], short_term: list[PickSummary]) -> tuple[str, str, str]:
    """(title, body_markdown, model_version) を返す。LLM未設定/失敗時は定型文でフォールバックする."""
    provider = resolve_feature_provider("note_publish")
    if not provider.is_configured or (not mid_term and not short_term):
        title = f"{note_date} AI分析ノート"
        body = "本日は紹介できる分析結果がありませんでした。" + DISCLAIMER
        return title, body, "unavailable"

    prompt = build_prompt(note_date, mid_term, short_term)
    try:
        raw = await provider.propose_daily_note(prompt=prompt)
    except LLMError:
        title = f"{note_date} AI分析ノート"
        body = "LLM呼び出しに失敗したため、本日の下書きを生成できませんでした。" + DISCLAIMER
        return title, body, f"{provider.provider_id}:error"

    title = str(raw.get("title", "")).strip() or f"{note_date} AI分析ノート"
    body = str(raw.get("body_markdown", "")).strip() + DISCLAIMER
    model_version = f"{provider.provider_id}:{provider.model_for('note_publish')}"
    return title, body, model_version
