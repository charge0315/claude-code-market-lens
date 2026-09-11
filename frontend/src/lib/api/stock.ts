// 株価 OHLC API（`backend/routers/stock.py`）の薄い型付きラッパ。

import { api } from '@/lib/api/client';

export type OhlcPeriod = '1mo' | '3mo' | '6mo' | '1y' | '2y';

export interface OhlcBar {
  time: string; // YYYY-MM-DD
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
}

export function fetchOhlc(symbol: string, period: OhlcPeriod = '6mo'): Promise<OhlcBar[]> {
  return api.get<OhlcBar[]>(`/stock/${encodeURIComponent(symbol)}/ohlc?period=${period}`);
}
