import { expect, test } from '@playwright/test';

// AI 判定の承認キュー（HITL）を API モックで操作する — LLM 未設定の CI では
// `POST /signals/run` が実際の判定を生成できないため、状態遷移
// proposed → approved → executed のみを検証する（実際の LLM 判定内容はローカルで確認済み）。

test('承認キューで承認→実約定報告まで操作できる（proposed → approved → executed）', async ({ page }) => {
  let status: 'proposed' | 'approved' | 'executed' = 'proposed';
  let fillReport: string | null = null;
  const baseSignal = {
    signal_id: 's1',
    symbol: '7203',
    evaluated_at: '2026-06-02T10:00:00+09:00',
    action: 'trim',
    entry: null,
    stop: 2800,
    target: 3200,
    confidence: 72,
    rationale: 'テスト根拠テキスト',
  };

  await page.route('**/api/portfolio', async (route) => {
    await route.fulfill({
      json: {
        success: true,
        data: {
          total_value: 0,
          total_cost: 0,
          total_gain_loss: 0,
          total_return_pct: 0,
          day_gain_loss: null,
          holdings: [],
          sector_allocations: [],
          holding_count: 0,
          updated_at: '2026-06-02T10:00:00+09:00',
        },
        error: null,
        meta: null,
      },
    });
  });

  await page.route('**/api/portfolio/eod-review', async (route) => {
    await route.fulfill({ json: { success: true, data: null, error: null, meta: null } });
  });

  await page.route(/\/api\/portfolio\/signals(\?.*)?$/, async (route) => {
    const url = new URL(route.request().url());
    const filterStatus = url.searchParams.get('status');
    const rows = filterStatus === null || filterStatus === status ? [{ ...baseSignal, status, fill_report: fillReport }] : [];
    await route.fulfill({ json: { success: true, data: rows, error: null, meta: null } });
  });

  await page.route('**/api/portfolio/signals/s1/approve', async (route) => {
    status = 'approved';
    await route.fulfill({ json: { success: true, data: { signal_id: 's1', status }, error: null, meta: null } });
  });

  await page.route('**/api/portfolio/signals/s1/report-fill', async (route) => {
    status = 'executed';
    fillReport = JSON.stringify({ executed_price: 3050, executed_quantity: 30, executed_at: '2026-06-02T15:00:00+09:00' });
    await route.fulfill({ json: { success: true, data: { signal_id: 's1', status }, error: null, meta: null } });
  });

  await page.goto('/portfolio');

  await expect(page.getByText('7203')).toBeVisible();
  await expect(page.getByText('テスト根拠テキスト')).toBeVisible();

  await page.getByRole('button', { name: '承認', exact: true }).click();
  await expect(page.getByText('該当する判定がありません')).toBeVisible();

  await page.getByRole('button', { name: '承認済み', exact: true }).click();
  await expect(page.getByRole('button', { name: '実約定を報告' })).toBeVisible();

  await page.getByRole('button', { name: '実約定を報告' }).click();
  await page.getByLabel('約定価格（円）').fill('3050');
  await page.getByLabel('約定株数').fill('30');
  await page.getByRole('button', { name: '報告する' }).click();

  await expect(page.getByText('該当する判定がありません')).toBeVisible();

  await page.getByRole('button', { name: '約定済み', exact: true }).click();
  await expect(page.getByText('約定報告済み')).toBeVisible();
});
