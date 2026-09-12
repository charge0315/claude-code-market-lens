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

export interface StockNote {
  code: string;
  note_title: string;
  content: string;
}

// ナレッジベース（Vault）ノートを本文込みで取得する。UI 表示専用（ポップアップ）で
// LLM プロンプトへは使わない（`backend/services/vault/brand_notes_service.get_raw_note_content`
// docstring 参照）。ノート未整備の銘柄では `null` を返す（エラーではない）。
export function fetchStockNote(symbol: string): Promise<StockNote | null> {
  return api.get<StockNote | null>(`/stock/${encodeURIComponent(symbol)}/note`);
}
