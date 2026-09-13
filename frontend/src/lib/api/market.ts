// 市況スナップショット API（`backend/routers/market.py`）の薄い型付きラッパ（🆕 P13）。

import { api } from '@/lib/api/client';

export type MarketStatus = '寄り前' | 'ザラ場中' | '引け後';

export interface IndexQuote {
  label: string;
  value: number;
  change: number;
  change_pct: number;
  // 🆕 P23: 直近の終値系列（簡易スパークライン表示用）。
  spark: number[];
}

export interface MarketSnapshot {
  indices: IndexQuote[];
  market_status: MarketStatus;
  updated_at: string;
}

export function fetchMarketSnapshot(): Promise<MarketSnapshot> {
  return api.get<MarketSnapshot>('/market/snapshot');
}
