"""通知（AI 売買判定の到達通知）と Web Push 購読の Pydantic スキーマ定義.

Market Lens `backend/models/notification.py` はトリガ元が「AI銘柄ピックの価格到達」
（`kind` が stop_loss/take_profit/buy_zone）という別設計のため流用できない。Alpha Forge の
トリガは `portfolio_signals`（`action != hold`）であり `kind` は trim/stop_loss/add を使う
（🆕、insert/dedupe/既読 の CRUD パターンのみ Market Lens `notification_service.py` を参考）。
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict

NotificationKind = Literal["trim", "stop_loss", "add"]


class Notification(BaseModel):
    """通知 1 件（`notifications` テーブルに対応）."""

    model_config = ConfigDict(frozen=True)

    notification_id: str
    run_date: str
    ticker: str
    kind: NotificationKind
    channel: str
    body: str  # JSON 文字列（symbol/action/entry/stop/target/confidence/rationale）
    created_at: str
    read_at: str | None = None


class PushSubscriptionRequest(BaseModel):
    """ブラウザの `PushSubscription` をそのまま受け取る登録リクエスト."""

    model_config = ConfigDict(frozen=True)

    endpoint: str
    p256dh: str
    auth: str
    user_agent: str | None = None


class UnsubscribeRequest(BaseModel):
    model_config = ConfigDict(frozen=True)

    endpoint: str
