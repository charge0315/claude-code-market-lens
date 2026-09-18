"""日次パイプラインログ（Markdown）の組み立て（🆕 P30）.

ユーザー指示: 候補プール銘柄一覧・絞り込み後銘柄一覧・4分析+MLの結果・合成スコア・LLM深掘り
ログ/見解・3値ブラケット・検証ゲート結果・予測台帳・決着記録・評価指標・再学習結果・
モデル入れ替えの有無を、1日1本の Obsidian ノートへまとめる。

外部由来テキストは扱わない（本モジュールが読むのは自システムが生成した数値・構造化データ・
LLM自身の応答テキストのみ）ため CLAUDE.md のプロンプトインジェクション境界の対象外だが、
出力先が個人アーカイブ（`Daily/AlphaForge/<日付>/pipeline_log.md`）である点は
`report_generator.py` と同じ（Market Lens 出力とは衝突しない専用パス）。
"""

from __future__ import annotations

import json
from typing import cast

from backend.models.pick import PickSummary
from backend.services.db import eval_db, model_registry_db, pick_outcome_db
from backend.services.db.inference_trace_db import list_runs_for_date
from backend.services.db.pick_pool_snapshot_db import list_pool_snapshots_for_date
from backend.services.ledger import prediction_ledger as pl

_HORIZONS: tuple[str, ...] = ("mid_term", "short_term")
_HORIZON_LABEL = {"mid_term": "中長期", "short_term": "短期"}
_STAGE_LABEL = {
    "collect": "現在値取得",
    "subscore": "サブスコア算出",
    "synthesis": "合成スコア算出",
    "llm_overlay": "LLM深掘り",
    "bracket": "3値ブラケット検証",
    "verify": "検証ゲート",
}


def _f(value: object) -> float | None:
    if isinstance(value, bool):
        return None
    return float(value) if isinstance(value, (int, float)) else None


def _pool_section(pool_rows: dict[str, list[dict[str, object]]]) -> str:
    """「候補プールで選出した銘柄一覧」「絞り込まれた銘柄一覧」「4分析+MLの結果」「合成スコア」."""
    lines = ["## 1. 候補プール・ショートリスト・4分析+MLスコア"]
    for horizon in _HORIZONS:
        rows = pool_rows.get(horizon) or []
        lines.append(f"\n### {_HORIZON_LABEL[horizon]}（候補プール {len(rows)} 銘柄）")
        if not rows:
            lines.append("該当データなし")
            continue
        shortlisted = [r for r in rows if r.get("is_shortlisted")]
        lines.append(f"ショートリスト（絞り込み後）: {', '.join(str(r['symbol']) for r in shortlisted) or 'なし'}")
        lines.append(
            "\n| 銘柄 | SL | 合成 | 方向性 | 一致度 | technical | trend | fundamental | sentiment | ML予測率 |"
        )
        lines.append("|:--|:--:|--:|:--|--:|--:|--:|--:|--:|--:|")
        for r in rows:
            breakdown = cast("dict[str, object]", r.get("score_breakdown") or {})
            mark = "✓" if r.get("is_shortlisted") else ""
            lines.append(
                f"| {r['symbol']} | {mark} | {_fmt(r.get('composite_score'))} | {r.get('direction') or '-'} "
                f"| {_fmt(r.get('concordance'))} | {_fmt(breakdown.get('technical'))} "
                f"| {_fmt(r.get('trend_score'))} | {_fmt(breakdown.get('fundamental'))} "
                f"| {_fmt(breakdown.get('sentiment'))} | {_fmt(r.get('ml_prediction_rate'))} |"
            )
    return "\n".join(lines)


def _fmt(value: object) -> str:
    num = _f(value)
    return f"{num:.1f}" if num is not None else "-"


def _extract_reason(final_stage: dict[str, object]) -> str:
    payload = cast("dict[str, object]", final_stage.get("payload") or {})
    for key in ("reason", "reasoning", "error"):
        val = payload.get(key)
        if isinstance(val, str) and val:
            return val
    return "詳細不明（応答形式不正等）"


def _deep_dive_lines(
    runs_by_horizon: dict[str, dict[str, list[dict[str, object]]]],
    ledger_by_pick_id: dict[str, PickSummary],
) -> str:
    """「LLMによる深堀りのログ・見解」「3値ブラケット値」「検証ゲートの結果」（run_idごと）."""
    lines = ["## 2. LLM深堀りログ・3値ブラケット・検証ゲート結果"]
    for horizon in _HORIZONS:
        runs = runs_by_horizon.get(horizon) or {}
        lines.append(f"\n### {_HORIZON_LABEL[horizon]}（実行 {len(runs)} 件）")
        if not runs:
            lines.append("該当データなし")
            continue
        for events in sorted(runs.values(), key=lambda e: str(e[0]["symbol"])):
            symbol = events[0]["symbol"]
            final = events[-1]
            pick_id = final.get("pick_id")
            pick = ledger_by_pick_id.get(str(pick_id)) if pick_id else None
            if final.get("status") == "done" and pick is not None:
                lines.append(
                    f"- **{symbol}**（採用）: entry={pick.entry:.1f} / stop={pick.stop:.1f} / "
                    f"target={pick.target:.1f} / 確度={pick.confidence:.0f}%（{pick.confidence_bucket}）\n"
                    f"  見解: {pick.rationale_text}"
                )
            else:
                stage_label = _STAGE_LABEL.get(str(final.get("stage")), str(final.get("stage")))
                lines.append(f"- **{symbol}**（却下・{stage_label}）: {_extract_reason(final)}")
    return "\n".join(lines)


def _ledger_section(ledger_rows: dict[str, list[PickSummary]]) -> str:
    """「予測台帳の記録」."""
    lines = ["## 3. 予測台帳の記録"]
    for horizon in _HORIZONS:
        rows = ledger_rows.get(horizon) or []
        lines.append(f"\n### {_HORIZON_LABEL[horizon]}（{len(rows)} 件）")
        if not rows:
            lines.append("本日の確定ピックなし")
            continue
        for p in rows:
            lines.append(
                f"- {p.symbol}: {p.direction} / entry={p.entry:.1f} stop={p.stop:.1f} target={p.target:.1f} "
                f"/ 確度={p.confidence:.0f}%（{p.confidence_bucket}） / pick_id={p.pick_id}"
            )
    return "\n".join(lines)


def _outcome_section(outcomes: list[dict[str, object]]) -> str:
    """「決着記録」."""
    lines = ["## 4. 決着記録", f"\n本日の決着件数: {len(outcomes)} 件"]
    if not outcomes:
        return "\n".join(lines)
    lines.append("\n| 銘柄 | ホライズン(日) | 結果 | 実現リターン | 超過リターン | 到達 |")
    lines.append("|:--|--:|:--:|--:|--:|:--|")
    for o in outcomes:
        win = "○的中" if o.get("win") else "×不的中"
        lines.append(
            f"| {o.get('symbol')} | {o.get('horizon_days')} | {win} | "
            f"{_fmt_pct(o.get('realized_return'))} | {_fmt_pct(o.get('excess_return'))} | {o.get('first_hit')} |"
        )
    return "\n".join(lines)


def _fmt_pct(value: object) -> str:
    num = _f(value)
    return f"{num * 100:+.2f}%" if num is not None else "-"


def _eval_section(eval_rows: list[dict[str, object]]) -> str:
    """「評価指標」."""
    lines = ["## 5. 評価指標（本日算出分）"]
    if not eval_rows:
        lines.append("本日算出された評価指標なし")
        return "\n".join(lines)
    lines.append("\n| scope | horizon | metric | value | n |")
    lines.append("|:--|--:|:--|--:|--:|")
    for r in eval_rows:
        lines.append(
            f"| {r.get('scope')} | {r.get('horizon_days') or '-'} | {r.get('metric_name')} | "
            f"{_fmt(r.get('metric_value'))} | {r.get('sample_n')} |"
        )
    return "\n".join(lines)


def _retraining_section(promotions: list[dict[str, object]]) -> str:
    """「再学習の結果」（週次/月次の昇格ゲート評価。本日実行分のみ）."""
    lines = ["## 6. 再学習・昇格ゲートの結果（本日評価分）"]
    if not promotions:
        lines.append("本日の再学習・昇格ゲート評価なし")
        return "\n".join(lines)
    verdict_label = {"propose_promote": "昇格提案", "reject": "却下", "hold": "見送り"}
    for p in promotions:
        rationale = json.loads(str(p.get("rationale") or "{}"))
        verdict = verdict_label.get(str(p.get("verdict")), str(p.get("verdict")))
        lines.append(
            f"- lane={p.get('lane')} challenger={p.get('challenger_version')} "
            f"champion={p.get('champion_version') or '未設定'} → **{verdict}**\n"
            f"  ホールドアウト差={_fmt(p.get('holdout_delta'))} / ペーパー日数={p.get('paper_days')} / "
            f"理由: {rationale.get('reason', '-')}"
        )
    return "\n".join(lines)


def _model_swap_section(champions: list[dict[str, object]]) -> str:
    """「学習したモデルを入れ替えたかどうか」（本日 champion が差し替わった lane のみ）."""
    lines = ["## 7. モデル入れ替え（champion 差し替え）"]
    if not champions:
        lines.append("本日の champion 入れ替えなし")
        return "\n".join(lines)
    for c in champions:
        lines.append(f"- lane={c.get('lane')} → champion={c.get('champion_version')}（{c.get('promoted_by')}）")
    return "\n".join(lines)


async def _ledger_rows_for_date(log_date: str) -> dict[str, list[PickSummary]]:
    return {
        horizon: await pl.list_picks(horizon_type=horizon, issued_from=f"{log_date}T00:00:00", limit=100)
        for horizon in _HORIZONS
    }


async def build_pipeline_log_markdown(log_date: str) -> tuple[str, dict[str, int]]:
    """指定日（JST）のパイプラインログを Markdown として組み立てる.

    件数サマリ（`PipelineLogResult` へそのまま渡せる dict）も併せて返し、`pipeline_log_service`
    が同じ集計を二重に問い合わせずに済むようにする（`report_generator.build_report_html` が
    `(html, charts)` を返すのと同じ構成）。
    """
    pool_rows = {h: await list_pool_snapshots_for_date(log_date, horizon_type=h) for h in _HORIZONS}
    runs_by_horizon = {h: await list_runs_for_date(log_date, horizon_type=h) for h in _HORIZONS}
    ledger_rows = await _ledger_rows_for_date(log_date)
    ledger_by_pick_id = {p.pick_id: p for rows in ledger_rows.values() for p in rows}

    outcomes = await pick_outcome_db.list_recent_reviews(since=f"{log_date}T00:00:00", limit=500)
    outcomes = [o for o in outcomes if str(o.get("resolved_at", ""))[:10] == log_date]

    eval_rows = await eval_db.list_eval_snapshots_for_date(log_date)

    all_promotions = await model_registry_db.list_promotions(limit=200)
    promotions = [p for p in all_promotions if str(p.get("evaluated_at", ""))[:10] == log_date]

    all_champions = await model_registry_db.list_champions()
    champions = [c for c in all_champions if str(c.get("promoted_at", ""))[:10] == log_date]

    header = (
        f"# {log_date} パイプライン実行ログ\n\n"
        "本日のピック生成〜決着・再学習までの実行結果を機械的に記録した個人用ログです。"
    )
    sections = [
        header,
        _pool_section(pool_rows),
        _deep_dive_lines(runs_by_horizon, ledger_by_pick_id),
        _ledger_section(ledger_rows),
        _outcome_section(outcomes),
        _eval_section(eval_rows),
        _retraining_section(promotions),
        _model_swap_section(champions),
    ]
    markdown = "\n\n".join(sections) + "\n"

    all_pool_rows = [row for rows in pool_rows.values() for row in rows]
    counts = {
        "candidate_count": len(all_pool_rows),
        "shortlisted_count": sum(1 for r in all_pool_rows if r.get("is_shortlisted")),
        "ledger_count": sum(len(rows) for rows in ledger_rows.values()),
        "resolved_outcome_count": len(outcomes),
        "eval_metric_count": len(eval_rows),
        "promotion_count": len(promotions),
        "champion_swap_count": len(champions),
    }
    return markdown, counts
