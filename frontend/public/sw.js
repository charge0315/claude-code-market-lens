// Alpha Forge Service Worker — Web Push 受信専用（P7d）。
// デスクトップ常駐前提のため PWA manifest / インストール導線は意図的に作らない
// （CLAUDE.md）。オフラインキャッシュ・ファイル配信の代行も行わない。

self.addEventListener('push', (event) => {
  let payload = {};
  try {
    payload = event.data ? event.data.json() : {};
  } catch {
    payload = {};
  }
  const title = payload.title || 'Alpha Forge';
  const options = {
    body: payload.body || '',
    data: payload.data || {},
    tag: (payload.data && payload.data.notification_id) || undefined,
  };
  event.waitUntil(self.registration.showNotification(title, options));
});

self.addEventListener('notificationclick', (event) => {
  event.notification.close();
  const targetUrl = '/notifications';
  event.waitUntil(
    self.clients.matchAll({ type: 'window', includeUncontrolled: true }).then((clientList) => {
      const existing = clientList.find((c) => new URL(c.url).pathname === targetUrl);
      if (existing) return existing.focus();
      return self.clients.openWindow(targetUrl);
    }),
  );
});
