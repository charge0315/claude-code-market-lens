import type { ReactNode } from 'react';
import { PageShell } from '@/components/ui/PageShell';
import { AiPicksSection } from '@/components/dashboard/AiPicksSection';
import { MarketTickerBar } from '@/components/dashboard/MarketTickerBar';

export default function DashboardPage(): ReactNode {
  return (
    <PageShell title="ダッシュボード">
      <MarketTickerBar />
      <AiPicksSection />
    </PageShell>
  );
}
