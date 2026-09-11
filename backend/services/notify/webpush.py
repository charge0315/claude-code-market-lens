"""Web Push 配信（VAPID 署名、`pywebpush` 使用）（🆕 N6、Market Lens に push 配信基盤は無し）.

VAPID 鍵が未設定（`settings.vapid_public_key`/`vapid_private_key` が空）の場合は配信自体を
スキップする（CLAUDE.md: 外部連携は未設定でも起動できる設計）。個々の購読への配信失敗
（期限切れ等）は他購読への配信を止めない。410/404 は `push_subscriptions.revoked` を立てて
以後の配信対象から除外する。`pywebpush` は同期 I/O のため `asyncio.to_thread` に逃がし、
DB 書き込み（イベントループ束縛の非同期エンジン）は呼び出し元スレッド（メインループ）へ
結果を持ち帰ってから行う。
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Literal

from pywebpush import WebPushException, webpush

from backend.config import settings
from backend.services.db.notification_db import list_active_subscriptions, revoke_subscription

logger = logging.getLogger(__name__)

_SendResult = Literal["ok", "revoke", "error"]
_REVOKE_STATUS_CODES = frozenset({404, 410})


async def send_to_all(*, title: str, body: str, data: dict[str, object] | None = None) -> int:
    """全アクティブ購読へ Push 通知を送信し、成功件数を返す。VAPID 未設定なら 0 件で即 return."""
    if not settings.vapid_public_key or not settings.vapid_private_key:
        return 0

    subscriptions = await list_active_subscriptions()
    payload = json.dumps({"title": title, "body": body, "data": data or {}}, ensure_ascii=False)

    sent = 0
    for sub in subscriptions:
        result = await asyncio.to_thread(_send_one, sub, payload)
        if result == "ok":
            sent += 1
        elif result == "revoke":
            await revoke_subscription(str(sub["endpoint"]))
    return sent


def _send_one(sub: dict[str, object], payload: str) -> _SendResult:
    """1 購読への同期送信（別スレッドで実行、DB へは触れない）."""
    try:
        webpush(
            subscription_info={
                "endpoint": str(sub["endpoint"]),
                "keys": {"p256dh": str(sub["p256dh"]), "auth": str(sub["auth"])},
            },
            data=payload,
            vapid_private_key=settings.vapid_private_key,
            vapid_claims={"sub": settings.vapid_subject},
        )
        return "ok"
    except WebPushException as e:
        status = e.response.status_code if e.response is not None else None
        if status in _REVOKE_STATUS_CODES:
            return "revoke"
        logger.warning("Web Push 配信に失敗: %s (status=%s)", e, status)
        return "error"
