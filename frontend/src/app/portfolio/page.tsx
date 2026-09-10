import type { ReactNode } from 'react';
import { PageShell } from '@/components/ui/PageShell';

export default function PortfolioPage(): ReactNode {
  return (
    <PageShell title="ポートフォリオ" phase="P7 / P8">
      <p>保有一覧、AI 判定（継続保有 / 一部利確 / 損切 / 買い増し）、通知履歴、承認キュー。</p>
    </PageShell>
  );
}
