import type { ReactNode } from 'react';
import { PageShell } from '@/components/ui/PageShell';
import { PortfolioOverview } from '@/components/portfolio/PortfolioOverview';
import { SignalQueue } from '@/components/portfolio/SignalQueue';
import { EodReviewPanel } from '@/components/portfolio/EodReviewPanel';

export default function PortfolioPage(): ReactNode {
  return (
    <PageShell title="ポートフォリオ" phase="P7">
      <p>保有一覧、AI 判定（継続保有 / 一部利確 / 損切 / 買い増し）、承認キュー、大引け後レビュー。</p>

      <section aria-labelledby="holdings-heading" style={{ marginTop: 'var(--spacing-2xl)' }}>
        <h2 id="holdings-heading" style={{ fontSize: 'var(--font-size-lg)', marginBottom: 'var(--spacing-sm)' }}>
          保有銘柄
        </h2>
        <PortfolioOverview />
      </section>

      <section aria-labelledby="signal-queue-heading" style={{ marginTop: 'var(--spacing-2xl)' }}>
        <h2 id="signal-queue-heading" style={{ fontSize: 'var(--font-size-lg)', marginBottom: 'var(--spacing-sm)' }}>
          AI 売買タイミング判定（承認キュー）
        </h2>
        <SignalQueue />
      </section>

      <section aria-labelledby="eod-review-heading" style={{ marginTop: 'var(--spacing-2xl)' }}>
        <h2 id="eod-review-heading" style={{ fontSize: 'var(--font-size-lg)', marginBottom: 'var(--spacing-sm)' }}>
          大引け後レビュー
        </h2>
        <EodReviewPanel />
      </section>
    </PageShell>
  );
}
