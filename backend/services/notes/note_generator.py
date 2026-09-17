"""日次noteドラフトの生成（🆕）.

本日の公式ピック（中長期・短期）から、entry/stop/target を一切含めない安全な素材のみを
LLM へ渡し、有料note記事の下書き（タイトル・本文）を生成する。具体的な売買価格や断定的な
投資指示は `NOTE_SCHEMA`（`services/llm/schemas.py`）のプロンプトレベルで禁止しているが、
LLM の出力を完全には制御できないため、生成後に軽量な価格表現チェックを行い、該当すれば
`has_price_mention_warning=True` を立てて人間のレビューで気づけるようにする（ブロックはしない
— 最終判断は承認ステップに委ねる、CLAUDE.md の承認制パターン）。

根拠を詳細に・情報ソースを明示する（ユーザー指示）ため、4分析（テクニカル/トレンド/
ファンダメンタル/センチメント）のスコア内訳・寄与度（`source_contributions`）・LLMリスク要因
までプロンプトに含める。素材はすべて `prediction_ledger` に既に永続化済みの値のみを使い、
新たな判断・推論はここでは行わない（CL-1: 台帳は予測時点の確定情報のみ）。
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass

from backend.models.market import IndexQuote
from backend.services.llm.errors import LLMError
from backend.services.llm.registry import resolve_feature_provider
from backend.services.picks.pick_analysis import PickAnalysis

__all__ = [
    "DISCLAIMER",
    "SOURCES_NOTE",
    "PickAnalysis",
    "PriorOutcomeReview",
    "build_prompt",
    "generate",
    "has_price_mention",
    "review_from_row",
]

DISCLAIMER = (
    "\n\n---\n\n"
    "※本記事はAIによる market データの分析結果を紹介する情報提供コンテンツであり、"
    "投資助言ではありません。具体的な売買の判断・タイミングはご自身の責任で行ってください。"
)

# 生成AIが自分でデータ出所を書くと不正確になりうるため、固定文言として必ず末尾に付与する
# （情報ソースの明示、ユーザー指示）。実際のデータ取得経路（CLAUDE.md アーキテクチャ）と一致させる。
SOURCES_NOTE = (
    "\n\n---\n\n"
    "### データソースについて\n"
    "本記事の分析は、以下のデータを基にAIが機械的に算出したスコア・指標をもとに作成しています。\n\n"
    "- 価格・テクニカル指標: yfinance（不足時はJ-Quants）の日次株価データ\n"
    "- ファンダメンタル指標: J-Quants財務データ、および独自ナレッジベース（Obsidian Vault）\n"
    "- センチメント・トレンド: ニュース見出し・トレンド分析エンジンの集計結果\n"
    "- 各分析の合成比率（寄与度）は銘柄ごとに変動します（記事中の「情報源内訳」参照）"
)

# 価格表現の混入チェック（ブロックはしない、レビュー時の注意喚起のみ）。
_PRICE_PATTERN = re.compile(r"[¥￥]\s?\d|\d+\s?円")

# 本文がこれ未満なら「出力トークン上限で本文が途中で切れた」等の異常とみなしフォールバックする
# （テンプレート準拠の多章立て記事は通常これよりずっと長くなるため、しきい値は保守的に低く取る）。
_MIN_BODY_LENGTH = 200

_DIRECTION_LABELS: dict[str, str] = {"bullish": "強気", "bearish": "弱気", "neutral": "中立"}
_HORIZON_TYPE_LABELS: dict[str, str] = {"mid_term": "中長期", "short_term": "短期"}
_FIRST_HIT_LABELS: dict[str, str] = {"target": "目標到達", "stop": "損切りライン到達", "none": "未到達"}
_SOURCE_LABELS: dict[str, str] = {
    "technical": "テクニカル",
    "trend": "トレンド",
    "fundamental": "ファンダメンタル",
    "sentiment": "センチメント",
    "ml": "機械学習モデル",
}


@dataclass(frozen=True)
class PriorOutcomeReview:
    """決着済みピック1件分の振り返り素材（entry/stop/targetは含めない、CL-1: 決着後の実測値のみ）."""

    symbol: str
    company_name: str | None
    horizon_type: str
    horizon_days: int
    direction: str
    realized_return: float
    excess_return: float
    mfe: float
    mae: float
    first_hit: str
    win: bool
    confidence_bucket: str


def review_from_row(row: Mapping[str, object]) -> PriorOutcomeReview:
    """`prediction_ledger.list_recent_outcome_reviews` の1行を `PriorOutcomeReview` へ変換する."""
    return PriorOutcomeReview(
        symbol=str(row["symbol"]),
        company_name=str(row["company_name"]) if row.get("company_name") else None,
        horizon_type=str(row["horizon_type"]),
        horizon_days=int(row["horizon_days"]),  # type: ignore[call-overload]
        direction=str(row["direction"]),
        realized_return=float(row["realized_return"]),  # type: ignore[arg-type]
        excess_return=float(row["excess_return"]),  # type: ignore[arg-type]
        mfe=float(row["mfe"]),  # type: ignore[arg-type]
        mae=float(row["mae"]),  # type: ignore[arg-type]
        first_hit=str(row["first_hit"]),
        win=bool(row["win"]),
        confidence_bucket=str(row["confidence_bucket"]),
    )


def _sub_score_line(sub_scores: dict[str, float]) -> str:
    if not sub_scores:
        return "（内訳データなし）"
    parts = [f"{_SOURCE_LABELS.get(k, k)}={v:.0f}" for k, v in sub_scores.items()]
    return "、".join(parts)


def _source_contribution_line(contributions: dict[str, object]) -> str:
    if not contributions:
        return "（内訳データなし）"
    parts: list[str] = []
    for key, value in contributions.items():
        if not isinstance(value, dict):
            continue
        share = value.get("weight_share")
        score = value.get("score")
        label = _SOURCE_LABELS.get(key, key)
        share_pct = f"{float(share) * 100:.0f}%" if isinstance(share, (int, float)) else "?"
        score_str = f"{float(score):.0f}" if isinstance(score, (int, float)) else "?"
        parts.append(f"{label}(寄与度{share_pct}・スコア{score_str})")
    return "、".join(parts) if parts else "（内訳データなし）"


def _pick_lines(picks: list[PickAnalysis]) -> list[str]:
    """entry/stop/target を含めない、根拠と情報源を詳細化した要約行を作る（LLMプロンプト素材）."""
    lines: list[str] = []
    for p in picks:
        name = f"（{p.company_name}）" if p.company_name else ""
        direction = _DIRECTION_LABELS.get(p.direction, p.direction)
        tags = "、".join(p.reasoning_tags) if p.reasoning_tags else "特になし"
        risks = "、".join(p.llm_risk_factors) if p.llm_risk_factors else "特筆すべきものなし"
        holding = f"{p.holding_period_days}営業日" if p.holding_period_days else "未設定"
        lines.append(
            f"- {p.symbol}{name}: 方向性={direction}, 合成スコア={p.composite_score:.1f}, "
            f"確度={p.confidence:.0f}（{p.confidence_bucket}）, 4分析の方向一致度={p.concordance:.2f}\n"
            f"  4分析スコア内訳: {_sub_score_line(p.sub_scores)}\n"
            f"  情報源内訳（寄与度・スコア）: {_source_contribution_line(p.source_contributions)}\n"
            f"  着眼点: {tags}\n"
            f"  想定保有期間の目安: {holding}\n"
            f"  リスク要因: {risks}\n"
            f"  分析コメント: {p.rationale_text}"
        )
    return lines


def _prior_review_lines(reviews: list[PriorOutcomeReview]) -> list[str]:
    """決着済みピックの振り返り行を作る（entry/stop/targetは一切含めない、決着後の実測値のみ）."""
    lines: list[str] = []
    for r in reviews:
        name = f"（{r.company_name}）" if r.company_name else ""
        direction = _DIRECTION_LABELS.get(r.direction, r.direction)
        horizon = _HORIZON_TYPE_LABELS.get(r.horizon_type, r.horizon_type)
        first_hit = _FIRST_HIT_LABELS.get(r.first_hit, r.first_hit)
        result = "的中" if r.win else "不的中"
        lines.append(
            f"- {r.symbol}{name}: {horizon}（{r.horizon_days}営業日）, 方向性={direction}, "
            f"判定={result}, 実現リターン={r.realized_return * 100:.2f}%, "
            f"TOPIX超過リターン={r.excess_return * 100:.2f}%, MFE={r.mfe * 100:.2f}%, "
            f"MAE={r.mae * 100:.2f}%, 先着={first_hit}, 確度バケット={r.confidence_bucket}"
        )
    return lines


def _market_lines(market: list[IndexQuote]) -> str:
    if not market:
        return "（本日は市況データを取得できませんでした）"
    lines = []
    for q in market:
        sign = "+" if q.change_pct >= 0 else ""
        lines.append(f"- {q.label}: {q.value:,.2f}（前日比 {sign}{q.change_pct:.2f}%）")
    return "\n".join(lines)


# `90_Meta/Templates/StockForNote.md`（Obsidian、ユーザー提供）の章立てを構造の土台として
# 踏襲する。同テンプレートには目安買値・損切りライン・目標利確（3値）とサマリーテーブルの
# 価格列が含まれるが、投資助言業への抵触を避けるため出力からは除外する（ユーザー確認済み）。
# 装飾的な数値例（NYダウの具体値・レーダー評価の「割安性/成長性」等の架空カテゴリ）は
# Alpha Forgeの実データ・実際の4分析軸（テクニカル/トレンド/ファンダメンタル/センチメント）に
# 置き換え、実在しない手法（LightGBM等）を捏造しないよう明示的に指示する。
_TEMPLATE_STRUCTURE_INSTRUCTIONS = """
以下の章立て・体裁で記事を構成してください（Obsidian/note.com双方に流用するため見出し構造を
厳守すること）。各章の内容は、後述の実データのみを根拠にし、実データが無い項目は正直に
「データなし」等と書いてください（数値・手法の捏造は禁止）。

## 1. 🌍 今日のグローバルトピックス＆寄り前市況
- 与えられた市況指標（日経平均・TOPIX・NYダウ・S&P500・USD/JPY・日経VI）の実際の値と前日比を
  表形式で示す
- 与えられた市況ニュースのメタ情報（あれば）を踏まえた寄り前の地合い解説

## 2. 📈 前日ピックの決着レビュー＆改善点
- 与えられた「直近で決着済みのピック」一覧（無ければ「本日は決着件数が少なく傾向分析には
  至らない」旨を正直に書くこと）を、的中/不的中・実現リターン・TOPIX超過リターン・MFE/MAE・
  先着（target/stop）の実測値に基づいて振り返る
- 傾向を無理に断定せず、実データから読み取れる範囲の考察に留める
- 次回のスクリーニング・確度較正に生かせる具体的な改善点を挙げる
- 具体的な買値・損切りライン等の価格提示や、断定的な投資指示は書かないこと（他章と同様）

## 3. 🤖 AIモデルの思考プロセス＆スクリーニング方針
- Alpha Forgeの実際の分析方式（テクニカル・トレンド・ファンダメンタル・センチメントの4分析を
  合成スコア化し、確度は過去の実測勝率に基づき較正している）を正確に説明すること
- 存在しない手法（LightGBM・SNS言及バズ等）を勝手に創作しないこと
- 本日抽出された銘柄群に共通する傾向があれば触れる

## 4. 📊 本日のAIピック一覧（サマリーテーブル）
- 列: 銘柄コード / 銘柄名 / 方向性 / 合成スコア / 確度 / 4分析の方向一致度 / 想定保有期間の目安
- 具体的な価格（買値・損切りライン・利確目標）は列に含めないこと

## 5. 🔍 各ピック銘柄の徹底解説＆チャート分析
- 銘柄ごとの見出しは必ず「### {証券コード}（{銘柄名}）」から始めること
  （例: ### 7203（トヨタ自動車）中長期・強気 — note.com貼り付け時にこの見出し直後へ
  証券コードのチャート自動挿入トリガーを機械的に挿入するため、見出しの表記ゆれは避けること）
- 銘柄ごとに: 4分析スコア内訳、情報源内訳（寄与度・スコア）、着眼点、分析コメント、
  リスク要因、方向一致度を踏まえた考察
- 「売買戦略」として具体的な価格水準を提示するのは禁止。定性的な観点（見るべきポイント・
  注意すべきシナリオ）に留めること

## 6. ⚖️ 4分析レーダー比較
- 全銘柄横断で、テクニカル・トレンド・ファンダメンタル・センチメントの4軸を比較する表
  （架空の「割安性」「成長性」等のカテゴリは使わず、実際に算出されている4分析軸のみ使うこと）

## 7. 📝 編集メモ・免責事項
- 有料記事化の際の構成案（どこから有料境界を引くか）への軽い言及
- 免責事項（投資助言ではない旨）
"""


def build_prompt(
    note_date: str,
    mid_term: list[PickAnalysis],
    short_term: list[PickAnalysis],
    *,
    market: list[IndexQuote] | None = None,
    news_block: str | None = None,
    prior_reviews: list[PriorOutcomeReview] | None = None,
) -> str:
    """note下書き生成用プロンプトを組み立てる（entry/stop/targetは一切渡さない）."""
    mid_lines = "\n".join(_pick_lines(mid_term)) or "（本日は該当なし）"
    short_lines = "\n".join(_pick_lines(short_term)) or "（本日は該当なし）"
    market_block = _market_lines(market or [])
    news = news_block or "（本日は市況ニュースのメタ情報がありません）"
    review_lines = "\n".join(_prior_review_lines(prior_reviews or [])) or "（直近で決着済みのピックはありません）"

    return (
        "あなたは日本株AI分析noteの執筆者です。以下は本日のAI銘柄ピック（中長期・短期）の"
        "詳細な分析結果です。具体的な買値・損切値・売値等の価格や、「買い時」「売るべき」等の"
        "断定的な投資指示は一切書かないでください。\n\n"
        f"{_TEMPLATE_STRUCTURE_INSTRUCTIONS}\n"
        "根拠はできるだけ詳細に記述し、単なる数値の列挙ではなく、なぜそのスコアになったと"
        "考えられるかの解釈・考察を加えてください。\n\n"
        f"## 市況指標（実データ）\n{market_block}\n\n"
        f"## 市況ニュース（メタ情報のみ）\n{news}\n\n"
        f"## 直近で決着済みのピック（前日レビュー用の実測値）\n{review_lines}\n\n"
        f"## {note_date} 中長期ピック分析\n{mid_lines}\n\n"
        f"## {note_date} 短期ピック分析\n{short_lines}\n\n"
        "submit_daily_note で記事タイトルと本文（Markdown）を提出してください。"
    )


def has_price_mention(body_markdown: str) -> bool:
    """本文に価格らしき表現が含まれるかを判定する（レビュー時の注意喚起用、ブロックはしない）."""
    return bool(_PRICE_PATTERN.search(body_markdown))


async def generate(
    note_date: str,
    mid_term: list[PickAnalysis],
    short_term: list[PickAnalysis],
    *,
    market: list[IndexQuote] | None = None,
    news_block: str | None = None,
    prior_reviews: list[PriorOutcomeReview] | None = None,
) -> tuple[str, str, str]:
    """(title, body_markdown, model_version) を返す。LLM未設定/失敗時は定型文でフォールバックする."""
    provider = resolve_feature_provider("note_publish")
    if not provider.is_configured or (not mid_term and not short_term):
        title = f"{note_date} AI分析ノート"
        body = "本日は紹介できる分析結果がありませんでした。" + DISCLAIMER
        return title, body, "unavailable"

    prompt = build_prompt(
        note_date, mid_term, short_term, market=market, news_block=news_block, prior_reviews=prior_reviews
    )
    try:
        raw = await provider.propose_daily_note(prompt=prompt)
    except LLMError:
        title = f"{note_date} AI分析ノート"
        body = "LLM呼び出しに失敗したため、本日の下書きを生成できませんでした。" + DISCLAIMER
        return title, body, f"{provider.provider_id}:error"

    title = str(raw.get("title", "")).strip() or f"{note_date} AI分析ノート"
    raw_body = str(raw.get("body_markdown", "")).strip()
    if len(raw_body) < _MIN_BODY_LENGTH:
        # 出力トークン上限到達等で本文が途中で切れ、ほぼ空のまま返ってくることがある
        # （実測: 2026-09-17、テンプレート準拠の多章立て記事で max_tokens 不足により発生）。
        # 免責文だけの記事を承認画面に出さないよう、フォールバックとして扱う。
        title = f"{note_date} AI分析ノート"
        body = "LLMの出力が不完全だったため、本日の下書きを生成できませんでした。" + DISCLAIMER
        return title, body, f"{provider.provider_id}:incomplete"
    body = raw_body + SOURCES_NOTE + DISCLAIMER
    model_version = f"{provider.provider_id}:{provider.model_for('note_publish')}"
    return title, body, model_version
