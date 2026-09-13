import type { ReactNode } from 'react';
import { PageShell } from '@/components/ui/PageShell';
import { ApiKeysPanel } from '@/components/settings/ApiKeysPanel';

export default function SettingsPage(): ReactNode {
  return (
    <PageShell title="設定">
      <section aria-labelledby="api-keys-heading">
        <h2 id="api-keys-heading" style={{ fontSize: 'var(--font-size-lg)', marginBottom: 'var(--spacing-sm)' }}>
          外部 API キー
        </h2>
        <p style={{ color: 'var(--color-text-secondary)', fontSize: 'var(--font-size-sm)', marginBottom: 'var(--spacing-lg)' }}>
          AI の判定・データ取得に使う外部サービスの API キーです。入力した値はサーバの <code>.env</code>{' '}
          にのみ保存され、画面には常に末尾4文字までしか表示されません。保存後、実際の動作に反映するには
          backend と celery worker / beat の再起動が必要です。
        </p>
        <ApiKeysPanel />
      </section>
    </PageShell>
  );
}
