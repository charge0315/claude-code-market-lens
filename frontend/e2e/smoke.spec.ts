import { expect, test } from '@playwright/test';

test('ルートはダッシュボードへリダイレクトし、免責フッタが常設される', async ({ page }) => {
  await page.goto('/');
  await expect(page).toHaveURL(/\/dashboard$/);
  await expect(page.getByRole('heading', { level: 1 })).toHaveText('ダッシュボード');
  await expect(page.getByRole('contentinfo')).toContainText('ブローカーへの発注を一切行いません');
});

test('主要 5 画面のナビゲーションが表示される', async ({ page }) => {
  await page.goto('/dashboard');
  const nav = page.getByRole('navigation');
  for (const label of ['ダッシュボード', '銘柄詳細', 'ポートフォリオ', 'モデルラボ', '通知センター']) {
    await expect(nav.getByRole('link', { name: label })).toBeVisible();
  }
});
