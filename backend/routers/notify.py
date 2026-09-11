"""通知（AI 売買判定の到達通知）一覧・既読化 + Web Push 購読 API + WS ライブ配信.

`plans/03_システム設計` §2.6。ライブ配信は `notifications` への INSERT をポーリングで検知する
（`routers/inference.py` の SSE と同じ理由 — 通知は celery ワーカー、API は別プロセスで動くため
プロセス内 pub/sub ではなく DB ポーリングが唯一の簡潔な配信経路になる）。WS は SSE と異なり
終端状態が無い常時接続のため、クライアント切断まで張りっぱなしでポーリングを続ける。
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime

from fastapi import APIRouter, HTTPException, Query, WebSocket, WebSocketDisconnect

from backend.config import settings
from backend.models.common import ApiResponse
from backend.models.notification import Notification, PushSubscriptionRequest, UnsubscribeRequest
from backend.services.db.notification_db import (
    list_notifications,
    list_notifications_since,
    mark_read,
    revoke_subscription,
    upsert_subscription,
)
from backend.services.jst_time import JST

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/notify", tags=["notify"])
# WS はプレフィックス無しの `/ws/notifications` を使うため router を分ける（`APIRouter.prefix`
# は websocket ルートにも適用されてしまうため）。
ws_router = APIRouter(tags=["notify"])

_WS_POLL_INTERVAL_SECONDS = 1.0


@router.get("/notifications", response_model=ApiResponse[list[Notification]], summary="通知一覧取得")
async def get_notifications(
    unread_only: bool = False, limit: int = Query(default=200, ge=1, le=1000)
) -> ApiResponse[list[Notification]]:
    """通知履歴を新しい順で返す。`unread_only=true` で未読のみ絞り込み."""
    rows = await list_notifications(unread_only=unread_only, limit=limit)
    return ApiResponse.ok([Notification.model_validate(r) for r in rows])


@router.patch("/notifications/{notification_id}/read", response_model=ApiResponse[Notification], summary="通知既読化")
async def mark_notification_read(notification_id: str) -> ApiResponse[Notification]:
    """指定した通知を既読にする."""
    row = await mark_read(notification_id)
    if row is None:
        raise HTTPException(status_code=404, detail=f"通知 {notification_id} が見つかりません")
    return ApiResponse.ok(Notification.model_validate(row))


@router.get("/vapid-key", response_model=ApiResponse[dict], summary="Web Push 公開鍵取得")
async def get_vapid_key() -> ApiResponse[dict]:
    """VAPID 公開鍵を返す（未設定なら空文字 — フロントは Push 購読 UI を非表示にする）."""
    return ApiResponse.ok({"public_key": settings.vapid_public_key})


@router.post("/subscribe", response_model=ApiResponse[dict], summary="Web Push 購読登録")
async def subscribe(req: PushSubscriptionRequest) -> ApiResponse[dict]:
    """ブラウザの `PushSubscription` を登録する（同一 endpoint は鍵を更新）."""
    await upsert_subscription(endpoint=req.endpoint, p256dh=req.p256dh, auth=req.auth, user_agent=req.user_agent)
    return ApiResponse.ok({"subscribed": True})


@router.post("/unsubscribe", response_model=ApiResponse[dict], summary="Web Push 購読解除")
async def unsubscribe(req: UnsubscribeRequest) -> ApiResponse[dict]:
    """購読を無効化し以後の配信対象から除外する."""
    ok = await revoke_subscription(req.endpoint)
    return ApiResponse.ok({"unsubscribed": ok})


@ws_router.websocket("/ws/notifications")
async def notifications_ws(websocket: WebSocket) -> None:
    """接続時刻より後に作成された通知をポーリングで検知し WS で配信し続ける."""
    await websocket.accept()
    last_seen = datetime.now(JST).isoformat(timespec="seconds")
    try:
        while True:
            rows = await list_notifications_since(last_seen)
            for row in rows:
                await websocket.send_json(dict(row))
                last_seen = str(row["created_at"])
            await asyncio.sleep(_WS_POLL_INTERVAL_SECONDS)
    except WebSocketDisconnect:
        logger.debug("通知 WS 切断")
