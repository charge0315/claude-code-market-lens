import type { ReactNode } from 'react';
import { PageShell } from '@/components/ui/PageShell';
import { PipelineTraceViewer } from '@/components/pipeline/PipelineTraceViewer';
import { StockOverview } from '@/components/stock-detail/StockOverview';

export default function StockDetailPage(): ReactNode {
  return (
    <PageShell title="銘柄詳細" phase="P8">
      <p>チャート（期間切替）+ 4 分析内訳 + AI 思考トレース（ライブ / リプレイ）。</p>

      <section aria-labelledby="overview-heading" style={{ marginTop: 'var(--spacing-2xl)' }}>
        <h2 id="overview-heading" style={{ fontSize: 'var(--font-size-lg)', marginBottom: 'var(--spacing-sm)' }}>
          チャート・4 分析内訳
        </h2>
        <StockOverview />
      </section>

      <section aria-labelledby="pipeline-heading" style={{ marginTop: 'var(--spacing-2xl)' }}>
        <h2 id="pipeline-heading" style={{ fontSize: 'var(--font-size-lg)', marginBottom: 'var(--spacing-sm)' }}>
          AI 推論トレース
        </h2>
        <PipelineTraceViewer />
      </section>
    </PageShell>
  );
}
