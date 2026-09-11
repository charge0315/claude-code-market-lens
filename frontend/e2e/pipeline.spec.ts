import { expect, test } from '@playwright/test';

// CI 環境の backend は起動直後で inference_traces が空のため、ここでは「実行が無い状態」の
// 空表示とライブ / リプレイ切替の基本動作のみを検証する（実データを使った DAG 遷移 / リプレイ
// 一致の確認は、LLM 設定済みの環境で実際にピックを生成してから手動 / 別途の統合テストで行う）。
test('銘柄詳細の AI 推論トレースが表示され、ライブ / リプレイを切り替えられる', async ({ page }) => {
  await page.goto('/stock-detail');

  await expect(page.getByRole('heading', { name: 'AI 推論トレース' })).toBeVisible();

  const toggle = page.getByRole('group', { name: '表示モード' });
  const liveButton = toggle.getByRole('button', { name: 'ライブ' });
  const replayButton = toggle.getByRole('button', { name: 'リプレイ' });
  await expect(liveButton).toBeVisible();
  await expect(replayButton).toBeVisible();
  await expect(liveButton).toHaveAttribute('aria-pressed', 'true');

  await replayButton.click();
  await expect(replayButton).toHaveAttribute('aria-pressed', 'true');
  await expect(liveButton).toHaveAttribute('aria-pressed', 'false');

  // 実行履歴が無い環境（CI の素の backend）では空状態メッセージが出る。
  const runSelect = page.getByRole('combobox', { name: '表示する推論実行' });
  await expect(runSelect).toBeVisible();
  const hasNoRuns = await runSelect.locator('option', { hasText: '実行履歴がありません' }).count();
  if (hasNoRuns > 0) {
    await expect(page.getByText('まだ推論実行がありません（ピック生成後に表示されます）')).toBeVisible();
  }
});
