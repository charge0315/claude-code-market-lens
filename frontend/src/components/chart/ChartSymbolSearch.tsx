'use client';

import { useRouter } from 'next/navigation';
import type { ReactNode } from 'react';
import { StockSearchBox } from '@/components/ui/StockSearchBox';
import type { TickerInfo } from '@/lib/api/stock';

// チャート画面用の銘柄検索。選択すると `?symbol=` を差し替えてチャートパネルを切り替える
// （`StockDetailSearchBox` と同じパターンだが遷移先が `/chart`）。

export function ChartSymbolSearch(): ReactNode {
  const router = useRouter();

  const handleSelect = (ticker: TickerInfo): void => {
    router.push(`/chart?symbol=${encodeURIComponent(ticker.code)}`);
  };

  return <StockSearchBox onSelect={handleSelect} />;
}
