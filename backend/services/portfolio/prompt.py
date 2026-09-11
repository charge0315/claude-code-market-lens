"""保有銘柄の売買タイミング判定プロンプト組み立て（🆕 P7b、PF-3）.

Market Lens に対応物はない（`ai_portfolio_*` は別機能、P7a 判断ログ参照）。
プロンプトへ注入するのは自システムが算出した定量値のみ（`portfolio_service` の評価結果・
ATR 目安レンジ）で、Vault 本文・ニュース本文は使わない（CLAUDE.md プロンプトインジェクション防御）。
"""

from __future__ import annotations

import json

from backend.services.picks.bracket import suggested_bracket


def build_portfolio_signal_prompt(
    *,
    symbol: str,
    quantity: int,
    avg_cost: float,
    current_price: float,
    unrealized_return_pct: float | None,
    atr: float | None,
    company_name: str | None,
    sector: str | None,
) -> str:
    """1 保有ロット分の判定プロンプトを組み立てる（forced tool-use `propose_portfolio_signal` 前提）."""
    lines: list[str] = [
        "あなたは日本株の保有ポジション管理を補助するアシスタントです。",
        "以下の保有銘柄について、継続保有(hold)・一部利確(trim)・損切(stop_loss)・買い増し(add)の"
        "いずれかを propose_portfolio_signal ツールで判定してください。",
        "",
        f"## 銘柄: {symbol}" + (f"（{company_name}）" if company_name else ""),
        f"- セクター: {sector or '不明'}",
        f"- 保有株数: {quantity} 株 / 平均取得単価: {avg_cost:.1f} 円",
        f"- 現在値: {current_price:.1f} 円",
    ]
    if unrealized_return_pct is not None:
        lines.append(f"- 含み損益率: {unrealized_return_pct * 100:.1f}%")

    if atr is not None and atr > 0:
        lines.append(
            f"- 目安ブラケット（ATR ベース、新規建てなら）: "
            f"{json.dumps(suggested_bracket(current_price, atr), ensure_ascii=False)}"
        )

    lines += [
        "",
        "## 制約",
        "- action=hold/trim/stop_loss のとき、stop_loss_price < 現在値 < take_profit_price を必ず満たすこと"
        "（entry は使わない）。",
        "- action=add のとき、stop_loss_price < entry < take_profit_price を必ず満たすこと。",
        "- 確信度は 0-100。方向感が不明瞭なら控えめに付けること。",
        "- 根拠は上記の定量情報のみを材料にすること。",
    ]
    return "\n".join(lines)
