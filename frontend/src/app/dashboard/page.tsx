import type { ReactNode } from 'react';
import { PageShell } from '@/components/ui/PageShell';

export default function DashboardPage(): ReactNode {
  return (
    <PageShell title="ダッシュボード" phase="P3 / P8">
      <p>本日のピック（中長期 / 短期タブ）、確度順、推奨買値 / 損切値 / 推奨売値、根拠プレビュー。</p>
    </PageShell>
  );
}
