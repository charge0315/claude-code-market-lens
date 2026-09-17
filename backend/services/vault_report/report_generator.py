"""Vaultアーカイブレポート（HTML）の組み立て（🆕）.

本日のAIピック（中長期・短期）について、ピック前日までのチャート・4分析（テクニカル/
トレンド/ファンダメンタル/センチメント）内訳・情報源内訳・根拠・リスク要因を1つのHTML
レポートにまとめる。個人用アーカイブ（Vault内で自分だけが見る）のため note.com 下書きと
違い LLM を介さず機械的に整形するだけ（ユーザー確認済み: 推奨買値/損切値/推奨売値の3値は
note.com向けと同じ方針でここでも含めない — `PickAnalysis` 自体に3値が無いため自然に満たす）。

外部由来テキスト（Vault本文・ニュース本文）は注入しない、frontmatterの構造化フィールドのみ
使う（CLAUDE.mdのプロンプトインジェクション境界と同じ方針。ここはLLMプロンプトではなく人間が
読むHTMLだが、XSS対策として全て `html.escape` する）。
"""

from __future__ import annotations

from html import escape

from backend.services.picks.pick_analysis import PickAnalysis
from backend.services.vault.news_digest_service import DailyNoteDigest
from backend.services.vault_report.chart_svg import render_chart_svg
from backend.services.vault_report.price_history import fetch_price_history_before

_DIRECTION_LABELS: dict[str, str] = {"bullish": "強気", "bearish": "弱気", "neutral": "中立"}
_SOURCE_LABELS: dict[str, str] = {
    "technical": "テクニカル",
    "trend": "トレンド",
    "fundamental": "ファンダメンタル",
    "sentiment": "センチメント",
    "ml": "機械学習モデル",
}

_STYLE = """
body { font-family: -apple-system, "Segoe UI", "Hiragino Sans", sans-serif; background: #f5ead8;
       color: #201e1d; max-width: 880px; margin: 0 auto; padding: 24px 16px; line-height: 1.7; }
h1 { font-size: 1.5rem; } h2 { font-size: 1.2rem; border-bottom: 2px solid #c67139; padding-bottom: 4px; }
h3 { font-size: 1.05rem; margin-bottom: 4px; }
.pick { background: #ebddc5; border-radius: 12px; padding: 16px; margin: 16px 0; }
.meta { color: #5c584f; font-size: 0.85rem; }
table.scores { border-collapse: collapse; margin: 8px 0; font-size: 0.85rem; }
table.scores td, table.scores th { border: 1px solid #c9bfa8; padding: 4px 8px; text-align: right; }
table.scores th { background: #f5ead8; text-align: center; }
.risk { color: #b32424; }
.disclaimer { color: #5c584f; font-size: 0.8rem; border-top: 1px solid #c9bfa8; padding-top: 12px; margin-top: 24px; }
"""


def _pick_section(p: PickAnalysis, chart_available: bool) -> str:
    name = f"（{escape(p.company_name)}）" if p.company_name else ""
    direction = _DIRECTION_LABELS.get(p.direction, p.direction)
    tags = "、".join(escape(t) for t in p.reasoning_tags) if p.reasoning_tags else "特になし"
    risks = "".join(f"<li>{escape(r)}</li>" for r in p.llm_risk_factors) or "<li>特筆すべきものなし</li>"
    holding = f"{p.holding_period_days}営業日" if p.holding_period_days else "未設定"
    chart_html = (
        f'<img src="charts/{escape(p.symbol)}.svg" alt="{escape(p.symbol)}のチャート" '
        f'style="max-width:100%;border-radius:8px;">'
        if chart_available
        else "<p class='meta'>チャート取得不可（データ不足）</p>"
    )

    score_rows = "".join(
        f"<tr><th>{_SOURCE_LABELS.get(k, k)}</th><td>{v:.0f}</td></tr>" for k, v in p.sub_scores.items()
    )
    contrib_rows = ""
    for key, value in p.source_contributions.items():
        if not isinstance(value, dict):
            continue
        share = value.get("weight_share")
        score = value.get("score")
        share_pct = f"{float(share) * 100:.0f}%" if isinstance(share, (int, float)) else "?"
        score_str = f"{float(score):.0f}" if isinstance(score, (int, float)) else "?"
        contrib_rows += (
            f"<tr><th>{_SOURCE_LABELS.get(key, key)}</th><td>寄与度{share_pct} / スコア{score_str}</td></tr>"
        )

    return f"""
<section class="pick">
  <h3>{escape(p.symbol)}{name}</h3>
  <p class="meta">方向性: {direction} / 合成スコア: {p.composite_score:.1f} /
     確度: {p.confidence:.0f}（{escape(p.confidence_bucket)}） /
     4分析の方向一致度: {p.concordance:.2f} / 想定保有期間の目安: {holding}</p>
  {chart_html}
  <table class="scores"><caption>4分析スコア内訳</caption>{score_rows}</table>
  <table class="scores"><caption>情報源内訳（寄与度・スコア）</caption>{contrib_rows}</table>
  <p><strong>着眼点:</strong> {tags}</p>
  <p><strong>分析コメント:</strong> {escape(p.rationale_text)}</p>
  <p class="risk"><strong>リスク要因:</strong></p>
  <ul class="risk">{risks}</ul>
</section>
"""


def _news_section(items: tuple[DailyNoteDigest, ...]) -> str:
    if not items:
        return "<p class='meta'>本日の市況ニュース（Vault日次ノート）はありません。</p>"
    rows = ""
    for item in items:
        title = escape(item.title) if item.title else "（タイトルなし）"
        category = f"[{escape(item.category)}] " if item.category else ""
        sources = "、".join(escape(s) for s in item.sources[:5]) if item.sources else "出典なし"
        rows += f"<li>{item.published_on.isoformat()} {category}{title}（{sources}）</li>"
    return f"<ul>{rows}</ul>"


async def build_report_html(
    report_date: str,
    mid_term: list[PickAnalysis],
    short_term: list[PickAnalysis],
    news: tuple[DailyNoteDigest, ...],
) -> tuple[str, dict[str, str]]:
    """(html, {symbol: svg}) を返す。チャートは銘柄ごとにピック前日までの終値から生成する."""
    charts: dict[str, str] = {}

    async def _render(picks: list[PickAnalysis]) -> str:
        sections = []
        for p in picks:
            series = await fetch_price_history_before(p.symbol, report_date)
            svg = render_chart_svg(f"{p.symbol}（{p.company_name}）" if p.company_name else p.symbol, series)
            if svg is not None:
                charts[p.symbol] = svg
            sections.append(_pick_section(p, chart_available=svg is not None))
        return "".join(sections) if sections else "<p class='meta'>本日は該当なし</p>"

    mid_html = await _render(mid_term)
    short_html = await _render(short_term)

    html = f"""<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="utf-8">
<title>{escape(report_date)} AIピック分析レポート</title>
<style>{_STYLE}</style>
</head>
<body>
<h1>{escape(report_date)} AIピック分析レポート（個人アーカイブ）</h1>
<p class="meta">AIピックの根拠・4分析内訳・情報源・チャート（ピック前日まで）をまとめた個人用記録です。</p>

<h2>本日の市況ニュース（メタ情報のみ）</h2>
{_news_section(news)}

<h2>中長期ピック</h2>
{mid_html}

<h2>短期ピック</h2>
{short_html}

<p class="disclaimer">
本レポートはAIによる分析結果の個人的な記録であり、投資助言ではありません。
推奨買値・損切値・推奨売値等の具体的な売買価格は本レポートには含まれません。
</p>
</body>
</html>
"""
    return html, charts
