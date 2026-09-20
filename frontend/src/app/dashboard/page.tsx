import type { ReactNode } from 'react';
import { PageShell } from '@/components/ui/PageShell';
import { AiPicksSection } from '@/components/dashboard/AiPicksSection';
import { MarketTickerBar } from '@/components/dashboard/MarketTickerBar';
import { PortfolioSummarySection } from '@/components/dashboard/PortfolioSummarySection';

export default function DashboardPage(): ReactNode {
  return (
    <PageShell title="ダッシュボード">
      <MarketTickerBar />

      <section aria-labelledby="portfolio-summary-heading" style={{ marginBottom: 'var(--spacing-2xl)' }}>
        <h2 id="portfolio-summary-heading" style={{ fontSize: 'var(--font-size-lg)', marginBottom: 'var(--spacing-sm)' }}>
          ポートフォリオ概況
        </h2>
        <PortfolioSummarySection />
      </section>

      <AiPicksSection />
    </PageShell>
  );
}
