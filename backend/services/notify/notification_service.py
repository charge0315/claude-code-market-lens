"""`portfolio_signals`（`action != hold`）を通知として記録し Web Push を配信する（🆕、N4/N6）.

Market Lens `notification_service.py` はトリガ元が「AI銘柄ピックの価格到達」（`stock_pick_service`
の実行結果に対する intraday 判定）という別物のため、insert/dedupe パターンのみ参考にした。
Alpha Forge のトリガはより単純 — `signal_service.evaluate_holding` が判定を確定させた
その場で呼ばれる（`action="hold"` は「変化なし」を意味するため通知しない）。重複防止は
`notifications` の `(run_date, ticker, kind)` 一意制約に委譲する。
"""

from __future__ import annotations

import json
import logging

from backend.services.db.notification_db import insert_notification
from backend.services.jst_time import today_jst
from backend.services.notify import webpush

logger = logging.getLogger(__name__)

_NOTIFIABLE_ACTIONS = frozenset({"trim", "stop_loss", "add"})

_ACTION_LABELS: dict[str, str] = {"trim": "一部利確", "stop_loss": "損切り", "add": "買い増し"}


async def notify_signal(
    *,
    symbol: str,
    action: str,
    stop: float,
    target: float,
    confidence: float,
    rationale: str,
    entry: float | None = None,
) -> str | None:
    """AI 売買タイミング判定を通知として記録し配信する（`action="hold"` は何もしない）.

    同日・同銘柄・同 action の通知は 1 件のみ（DB 一意制約）。新規作成できた場合のみ
    Web Push を配信する（重複判定を通知ごとに DB 一意制約へ委譲しているため、ここでは
    「新規作成できたか」だけを配信トリガに使えば良い）。
    """
    if action not in _NOTIFIABLE_ACTIONS:
        return None

    body = json.dumps(
        {
            "symbol": symbol,
            "action": action,
            "entry": entry,
            "stop": stop,
            "target": target,
            "confidence": confidence,
            "rationale": rationale,
        },
        ensure_ascii=False,
    )
    notification_id = await insert_notification(ticker=symbol, kind=action, body=body, run_date=today_jst())
    if notification_id is None:
        return None

    label = _ACTION_LABELS[action]
    await webpush.send_to_all(
        title=f"{symbol} — {label}判定",
        body=rationale,
        data={"notification_id": notification_id, "symbol": symbol, "action": action},
    )
    return notification_id
