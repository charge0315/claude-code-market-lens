import { expect, test, type WebSocketRoute } from '@playwright/test';

// WS はモックし、実バックエンド（LLM 未設定の CI）に依存せず配信 E2E を成立させる
// （Playwright の routeWebSocket はブラウザの WebSocket API 層でインターセプトするため、
// next.config.mjs の /ws リライトより手前で完結する）。

test('通知センターで WS ライブ配信された通知が即座に表示され、既読にできる', async ({ page }) => {
  await page.route('**/api/notify/notifications*', async (route) => {
    await route.fulfill({ json: { success: true, data: [], error: null, meta: null } });
  });

  // page.goto の前に接続が確立するため、以降の利用時点では必ず代入済み（definite assignment）。
  let ws!: WebSocketRoute;
  await page.routeWebSocket('**/ws/notifications', (route) => {
    ws = route;
  });

  await page.goto('/notifications');

  await expect(page.getByText('通知はありません')).toBeVisible();
  await expect(page.getByRole('status')).toHaveText('ライブ接続中');

  const notification = {
    notification_id: 'n1',
    run_date: '2026-06-02',
    ticker: '7203',
    kind: 'trim',
    channel: 'in_app',
    body: JSON.stringify({
      symbol: '7203',
      action: 'trim',
      entry: null,
      stop: 2800,
      target: 3200,
      confidence: 72,
      rationale: 'テスト根拠テキスト',
    }),
    created_at: '2026-06-02T10:00:00+09:00',
    read_at: null,
  };
  ws.send(JSON.stringify(notification));

  await expect(page.getByText('7203')).toBeVisible();
  await expect(page.getByText('一部利確')).toBeVisible();
  await expect(page.getByText('テスト根拠テキスト')).toBeVisible();

  await page.route('**/api/notify/notifications/n1/read', async (route) => {
    await route.fulfill({
      json: {
        success: true,
        data: { ...notification, read_at: '2026-06-02T10:05:00+09:00' },
        error: null,
        meta: null,
      },
    });
  });

  await page.getByRole('button', { name: '既読にする' }).click();
  await expect(page.getByRole('button', { name: '既読にする' })).toHaveCount(0);
});
