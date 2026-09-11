'use client';

import { useEffect, useState, type ReactNode } from 'react';
import {
  fetchNotifications,
  markNotificationRead,
  parseNotificationBody,
  type AppNotification,
} from '@/lib/api/notifications';
import { subscribeWs } from '@/lib/realtime/ws';
import { disablePushNotifications, enablePushNotifications, isPushEnabled, isPushSupported } from '@/lib/push/registerServiceWorker';
import './notify.css';

const KIND_LABELS: Record<AppNotification['kind'], string> = {
  trim: '一部利確',
  stop_loss: '損切り',
  add: '買い増し',
};

function isAppNotification(value: unknown): value is AppNotification {
  return typeof value === 'object' && value !== null && 'notification_id' in value && 'ticker' in value;
}

function upsertByNotificationId(prev: AppNotification[], incoming: AppNotification): AppNotification[] {
  if (prev.some((n) => n.notification_id === incoming.notification_id)) return prev;
  return [incoming, ...prev];
}

export function NotificationCenter(): ReactNode {
  const [notifications, setNotifications] = useState<AppNotification[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [wsStatus, setWsStatus] = useState<'open' | 'closed' | 'reconnecting'>('closed');
  // isPushSupported() は window/navigator に依存するため、レンダー中に直接呼ぶと SSR（false）と
  // クライアント初回描画（真の対応状況）が食い違いハイドレーションエラーになる。マウント後の
  // useEffect でのみ確定させ、それまでは両者と同じ false を初期値にする。
  const [pushSupported, setPushSupported] = useState(false);
  const [pushEnabled, setPushEnabled] = useState<boolean | null>(null);
  const [pushBusy, setPushBusy] = useState(false);

  useEffect(() => {
    fetchNotifications({ limit: 100 })
      .then(setNotifications)
      .catch(() => setError('通知一覧の取得に失敗しました'));
  }, []);

  useEffect(() => {
    const subscription = subscribeWs('/ws/notifications', {
      onMessage: (data) => {
        if (isAppNotification(data)) {
          setNotifications((prev) => upsertByNotificationId(prev, data));
        }
      },
      onStatus: setWsStatus,
    });
    return () => subscription.close();
  }, []);

  useEffect(() => {
    Promise.resolve(isPushSupported()).then((supported) => {
      setPushSupported(supported);
      Promise.resolve(supported ? isPushEnabled() : false).then(setPushEnabled);
    });
  }, []);

  const handleMarkRead = (notificationId: string): void => {
    markNotificationRead(notificationId)
      .then((updated) => {
        setNotifications((prev) => prev.map((n) => (n.notification_id === notificationId ? updated : n)));
      })
      .catch(() => setError('既読化に失敗しました'));
  };

  const handleTogglePush = (): void => {
    setPushBusy(true);
    const action = pushEnabled ? disablePushNotifications().then(() => false) : enablePushNotifications();
    action
      .then(setPushEnabled)
      .catch(() => setError('Push 通知の設定変更に失敗しました'))
      .finally(() => setPushBusy(false));
  };

  return (
    <div className="notification-center">
      <div className="notification-center-toolbar">
        <span className="notification-center-status" role="status">
          {wsStatus === 'open' ? 'ライブ接続中' : wsStatus === 'reconnecting' ? '再接続中…' : '未接続'}
        </span>
        {pushSupported && (
          <button type="button" onClick={handleTogglePush} disabled={pushBusy || pushEnabled === null}>
            {pushEnabled ? 'Push 通知を無効化' : 'Push 通知を有効化'}
          </button>
        )}
      </div>

      {error && <p className="signal-queue-error">{error}</p>}

      {notifications.length === 0 ? (
        <p className="signal-queue-empty">通知はありません</p>
      ) : (
        <ul className="notification-list">
          {notifications.map((notification) => {
            const body = parseNotificationBody(notification);
            return (
              <li
                key={notification.notification_id}
                className={notification.read_at ? 'notification-item' : 'notification-item notification-item--unread'}
              >
                <div className="notification-item-header">
                  <span className="notification-item-ticker">{notification.ticker}</span>
                  <span className="notification-item-kind">{KIND_LABELS[notification.kind]}</span>
                  <span className="notification-item-time">{notification.created_at}</span>
                </div>
                {body && <p className="notification-item-rationale">{body.rationale}</p>}
                {!notification.read_at && (
                  <button type="button" onClick={() => handleMarkRead(notification.notification_id)}>
                    既読にする
                  </button>
                )}
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}
