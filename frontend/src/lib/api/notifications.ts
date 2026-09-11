// 通知 API（`backend/routers/notify.py`）の薄い型付きラッパ。

import { api } from '@/lib/api/client';

export type NotificationKind = 'trim' | 'stop_loss' | 'add';

export interface AppNotification {
  notification_id: string;
  run_date: string;
  ticker: string;
  kind: NotificationKind;
  channel: string;
  body: string; // JSON 文字列（symbol/action/entry/stop/target/confidence/rationale）
  created_at: string;
  read_at: string | null;
}

export interface NotificationBody {
  symbol: string;
  action: NotificationKind;
  entry: number | null;
  stop: number;
  target: number;
  confidence: number;
  rationale: string;
}

export function parseNotificationBody(notification: AppNotification): NotificationBody | null {
  try {
    return JSON.parse(notification.body) as NotificationBody;
  } catch {
    return null;
  }
}

export function fetchNotifications(params?: { unreadOnly?: boolean; limit?: number }): Promise<AppNotification[]> {
  const q = new URLSearchParams();
  if (params?.unreadOnly) q.set('unread_only', 'true');
  if (params?.limit) q.set('limit', String(params.limit));
  const qs = q.toString();
  return api.get<AppNotification[]>(`/notify/notifications${qs ? `?${qs}` : ''}`);
}

export function markNotificationRead(notificationId: string): Promise<AppNotification> {
  return api.patch<AppNotification>(`/notify/notifications/${encodeURIComponent(notificationId)}/read`);
}

export function fetchVapidPublicKey(): Promise<{ public_key: string }> {
  return api.get('/notify/vapid-key');
}

export interface PushSubscriptionRequest {
  endpoint: string;
  p256dh: string;
  auth: string;
  user_agent?: string | null;
}

export function subscribePush(sub: PushSubscriptionRequest): Promise<{ subscribed: boolean }> {
  return api.post('/notify/subscribe', sub);
}

export function unsubscribePush(endpoint: string): Promise<{ unsubscribed: boolean }> {
  return api.post('/notify/unsubscribe', { endpoint });
}
