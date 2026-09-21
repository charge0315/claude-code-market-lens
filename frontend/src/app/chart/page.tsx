import type { ReactNode } from 'react';
import { PageShell } from '@/components/ui/PageShell';
import { ChartPanel } from '@/components/chart/ChartPanel';
import { ChartSymbolSearch } from '@/components/chart/ChartSymbolSearch';
import { PickedTickersList } from '@/components/stock-detail/PickedTickersList';
import '@/components/chart/chart.css';

// 銘柄詳細画面（`/stock-detail`）は AI 推論実行が存在する銘柄しかチャートを表示しない
// 制約があるため、AI ピック対象外も含めて任意の銘柄のチャートを素早く見るための
// 独立画面として新設（🆕、movement-chart のダッシュボード構成を参考にした）。

export default async function ChartPage({
  searchParams,
}: {
  searchParams: Promise<{ symbol?: string }>;
}): Promise<ReactNode> {
  const { symbol } = await searchParams;
  const selectedSymbol = symbol ?? null;

  return (
    <PageShell title="チャート">
      <p>銘柄を検索して株価チャートを表示します。AI ピック対象外の銘柄も含めて閲覧できます。</p>

      <div className="chart-page-layout" style={{ marginTop: 'var(--spacing-2xl)' }}>
        <div className="chart-page-sidebar">
          <section aria-labelledby="chart-search-heading">
            <h2 id="chart-search-heading" style={{ fontSize: 'var(--font-size-lg)', marginBottom: 'var(--spacing-sm)' }}>
              銘柄検索
            </h2>
            <ChartSymbolSearch />
          </section>

          <section aria-labelledby="chart-quick-heading">
            <h2 id="chart-quick-heading" style={{ fontSize: 'var(--font-size-lg)', marginBottom: 'var(--spacing-sm)' }}>
              ピック・保有銘柄から選ぶ
            </h2>
            <PickedTickersList selectedSymbol={selectedSymbol} basePath="/chart" />
          </section>
        </div>

        <section aria-labelledby="chart-panel-heading">
          <h2 id="chart-panel-heading" style={{ fontSize: 'var(--font-size-lg)', marginBottom: 'var(--spacing-sm)' }}>
            チャート
          </h2>
          <ChartPanel symbol={selectedSymbol} />
        </section>
      </div>
    </PageShell>
  );
}
