'use client';

import { useRouter } from 'next/navigation';
import type { ReactNode } from 'react';
import { StockSearchBox } from '@/components/ui/StockSearchBox';
import type { TickerInfo } from '@/lib/api/stock';

// 銘柄詳細画面用の銘柄検索（ユーザー指示）。選択すると同じ画面のまま
// `?symbol=` を差し替えてチャート・4分析内訳・AI推論トレースを切り替える。

export function StockDetailSearchBox(): ReactNode {
  const router = useRouter();

  const handleSelect = (ticker: TickerInfo): void => {
    router.push(`/stock-detail?symbol=${encodeURIComponent(ticker.code)}`);
  };

  return <StockSearchBox onSelect={handleSelect} />;
}
