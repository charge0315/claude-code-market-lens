// Service Worker 登録 + Web Push 購読の橋渡し（P7d）。
// デスクトップ常駐前提のため PWA manifest / インストール導線は意図的に作らない（CLAUDE.md）。

import { fetchVapidPublicKey, subscribePush, unsubscribePush } from '@/lib/api/notifications';

const SW_PATH = '/sw.js';

export function isPushSupported(): boolean {
  return typeof window !== 'undefined' && 'serviceWorker' in navigator && 'PushManager' in window;
}

function urlBase64ToUint8Array(base64String: string): Uint8Array {
  const padding = '='.repeat((4 - (base64String.length % 4)) % 4);
  const base64 = (base64String + padding).replace(/-/g, '+').replace(/_/g, '/');
  const rawData = window.atob(base64);
  const outputArray = new Uint8Array(rawData.length);
  for (let i = 0; i < rawData.length; i += 1) {
    outputArray[i] = rawData.charCodeAt(i);
  }
  return outputArray;
}

/** Push 通知を有効化する。VAPID 未設定・権限拒否・非対応ブラウザでは false を返す。 */
export async function enablePushNotifications(): Promise<boolean> {
  if (!isPushSupported()) return false;

  const { public_key: publicKey } = await fetchVapidPublicKey();
  if (!publicKey) return false;

  const permission = await Notification.requestPermission();
  if (permission !== 'granted') return false;

  await navigator.serviceWorker.register(SW_PATH);
  const registration = await navigator.serviceWorker.ready;
  const subscription = await registration.pushManager.subscribe({
    userVisibleOnly: true,
    // TS 5.9 の lib.dom は Uint8Array<ArrayBuffer> を要求するが、`new Uint8Array(n)` は
    // `Uint8Array<ArrayBufferLike>` と推論される既知の型定義ギャップ（実行時は問題ない）。
    applicationServerKey: urlBase64ToUint8Array(publicKey) as BufferSource,
  });

  const json = subscription.toJSON();
  const p256dh = json.keys?.p256dh;
  const auth = json.keys?.auth;
  if (!p256dh || !auth) return false;

  await subscribePush({ endpoint: subscription.endpoint, p256dh, auth, user_agent: navigator.userAgent });
  return true;
}

export async function disablePushNotifications(): Promise<void> {
  if (!isPushSupported()) return;
  const registration = await navigator.serviceWorker.getRegistration(SW_PATH);
  const subscription = await registration?.pushManager.getSubscription();
  if (!subscription) return;
  await unsubscribePush(subscription.endpoint);
  await subscription.unsubscribe();
}

export async function isPushEnabled(): Promise<boolean> {
  if (!isPushSupported()) return false;
  const registration = await navigator.serviceWorker.getRegistration(SW_PATH);
  const subscription = await registration?.pushManager.getSubscription();
  return subscription !== null && subscription !== undefined;
}
