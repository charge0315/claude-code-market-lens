import type { ReactNode } from 'react';
import { PageShell } from '@/components/ui/PageShell';
import { PipelineTraceViewer } from '@/components/pipeline/PipelineTraceViewer';

export default function StockDetailPage(): ReactNode {
  return (
    <PageShell title="銘柄詳細" phase="P6 / P8">
      <p>チャート（複数時間軸）+ 4 分析内訳 + AI 思考トレース（ライブ / リプレイ）。</p>

      <section aria-labelledby="pipeline-heading" style={{ marginTop: 'var(--spacing-2xl)' }}>
        <h2 id="pipeline-heading" style={{ fontSize: 'var(--font-size-lg)', marginBottom: 'var(--spacing-sm)' }}>
          AI 推論トレース
        </h2>
        <PipelineTraceViewer />
      </section>
    </PageShell>
  );
}
