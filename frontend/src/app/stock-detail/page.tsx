import type { ReactNode } from 'react';
import { PageShell } from '@/components/ui/PageShell';
import { PipelineTraceViewer } from '@/components/pipeline/PipelineTraceViewer';
import { PickedTickersList } from '@/components/stock-detail/PickedTickersList';
import { StockDetailSearchBox } from '@/components/stock-detail/StockDetailSearchBox';
import { StockOverview } from '@/components/stock-detail/StockOverview';

export default async function StockDetailPage({
  searchParams,
}: {
  searchParams: Promise<{ symbol?: string }>;
}): Promise<ReactNode> {
  const { symbol } = await searchParams;
  const selectedSymbol = symbol ?? null;

  return (
    <PageShell title="銘柄詳細">
      <p>ピック銘柄一覧 + チャート（期間切替）+ 4 分析内訳 + AI 思考トレース（ライブ / リプレイ）。</p>

      <section aria-labelledby="stock-search-heading" style={{ marginTop: 'var(--spacing-2xl)' }}>
        <h2 id="stock-search-heading" style={{ fontSize: 'var(--font-size-lg)', marginBottom: 'var(--spacing-sm)' }}>
          銘柄検索
        </h2>
        <StockDetailSearchBox />
      </section>

      <section aria-labelledby="tickers-heading" style={{ marginTop: 'var(--spacing-2xl)' }}>
        <h2 id="tickers-heading" style={{ fontSize: 'var(--font-size-lg)', marginBottom: 'var(--spacing-sm)' }}>
          ピックされた銘柄
        </h2>
        <PickedTickersList selectedSymbol={selectedSymbol} />
      </section>

      <section aria-labelledby="overview-heading" style={{ marginTop: 'var(--spacing-2xl)' }}>
        <h2 id="overview-heading" style={{ fontSize: 'var(--font-size-lg)', marginBottom: 'var(--spacing-sm)' }}>
          チャート・4 分析内訳
        </h2>
        <StockOverview key={selectedSymbol} symbol={selectedSymbol} />
      </section>

      <section aria-labelledby="pipeline-heading" style={{ marginTop: 'var(--spacing-2xl)' }}>
        <h2 id="pipeline-heading" style={{ fontSize: 'var(--font-size-lg)', marginBottom: 'var(--spacing-sm)' }}>
          AI 推論トレース
        </h2>
        <PipelineTraceViewer key={selectedSymbol} symbol={selectedSymbol} />
      </section>
    </PageShell>
  );
}
