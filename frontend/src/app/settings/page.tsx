import type { ReactNode } from 'react';
import { PageShell } from '@/components/ui/PageShell';
import { ApiKeysPanel } from '@/components/settings/ApiKeysPanel';
import { LLMProviderPanel } from '@/components/settings/LLMProviderPanel';

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

      <section aria-labelledby="llm-providers-heading" style={{ marginTop: 'var(--spacing-xl)' }}>
        <h2 id="llm-providers-heading" style={{ fontSize: 'var(--font-size-lg)', marginBottom: 'var(--spacing-sm)' }}>
          LLM プロバイダ設定
        </h2>
        <p style={{ color: 'var(--color-text-secondary)', fontSize: 'var(--font-size-sm)', marginBottom: 'var(--spacing-lg)' }}>
          機能ごとに、実際の判定を左右する「公式プロバイダ」と、同じ内容を並行判定させ比較表示する
          だけの「シャドウプロバイダ」（複数併用可）を選べます。APIキーが未設定のプロバイダを選ぶと
          その機能は動作しません。保存後の反映には backend と celery worker / beat の再起動が必要です。
        </p>
        <LLMProviderPanel />
      </section>
    </PageShell>
  );
}
