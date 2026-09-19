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

// テクニカル指標のクロスイベント（🆕、ゴールデンクロス/デッドクロス・MACDクロス）。
// チャート上のマーカー描画・hoverツールチップに使う。
export type ChartEventKind = 'golden_cross' | 'dead_cross' | 'macd_bullish_cross' | 'macd_bearish_cross';

export interface ChartEvent {
  date: string; // YYYY-MM-DD
  kind: ChartEventKind;
  label: string;
}

export interface OhlcResponse {
  bars: OhlcBar[];
  events: ChartEvent[];
}

export function fetchOhlc(symbol: string, period: OhlcPeriod = '6mo'): Promise<OhlcResponse> {
  return api.get<OhlcResponse>(`/stock/${encodeURIComponent(symbol)}/ohlc?period=${period}`);
}

// 🆕 P26: ポートフォリオの買い/売りフォームが開いた時点の最新値を初期値にするための
// 軽量エンドポイント。取得失敗時は price 等が null で返る（フォームは手入力にフォールバック）。
export interface Quote {
  symbol: string;
  price: number | null;
  prev_close: number | null;
  change_pct: number | null;
}

export function fetchQuote(symbol: string): Promise<Quote> {
  return api.get<Quote>(`/stock/${encodeURIComponent(symbol)}/quote`);
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

// 🆕 P26: 証券コード/銘柄名の部分一致検索（ポートフォリオへの銘柄追加用）。
export interface TickerInfo {
  code: string;
  name: string;
  sector: string | null;
}

export function searchStocks(query: string): Promise<TickerInfo[]> {
  return api.get<TickerInfo[]>(`/stock/search?q=${encodeURIComponent(query)}`);
}
