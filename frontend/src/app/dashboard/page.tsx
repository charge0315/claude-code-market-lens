import type { ReactNode } from 'react';
import { PageShell } from '@/components/ui/PageShell';
import { MarketTickerBar } from '@/components/dashboard/MarketTickerBar';
import { PicksBoard } from '@/components/dashboard/PicksBoard';

export default function DashboardPage(): ReactNode {
  return (
    <PageShell title="ダッシュボード">
      <MarketTickerBar />
      <PicksBoard />
    </PageShell>
  );
}
