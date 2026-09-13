// ポートフォリオ API（`backend/routers/portfolio.py`）の薄い型付きラッパ。

import { api } from '@/lib/api/client';

export interface PortfolioHolding {
  holding_id: string;
  symbol: string;
  company_name: string | null;
  sector: string | null;
  quantity: number;
  avg_cost: number;
  current_price: number | null;
  current_value: number | null;
  cost_basis: number;
  gain_loss: number | null;
  return_pct: number | null;
  acquired_at: string;
}

export interface SectorAllocation {
  sector: string;
  value: number;
  pct: number;
}

export interface PortfolioSummary {
  total_value: number;
  total_cost: number;
  total_gain_loss: number;
  total_return_pct: number;
  day_gain_loss: number | null;
  holdings: PortfolioHolding[];
  sector_allocations: SectorAllocation[];
  holding_count: number;
  updated_at: string;
}

export type PortfolioSignalAction = 'hold' | 'trim' | 'stop_loss' | 'add';
export type PortfolioSignalStatus = 'proposed' | 'approved' | 'rejected' | 'executed';

// 🆕 AI 売買タイミング判定の Gemini（challenger）版。比較参考用で承認フローには関与しない。
export interface PortfolioSignalShadow {
  shadow_id: string;
  signal_id: string;
  challenger_version: string;
  action: PortfolioSignalAction;
  entry: number | null;
  stop: number;
  target: number;
  confidence: number;
  reasoning: string;
  created_at: string;
}

export interface PortfolioSignal {
  signal_id: string;
  symbol: string;
  evaluated_at: string;
  action: PortfolioSignalAction;
  entry: number | null;
  stop: number;
  target: number;
  confidence: number;
  rationale: string;
  status: PortfolioSignalStatus;
  fill_report: string | null;
  gemini_shadow: PortfolioSignalShadow | null;
}

export interface HeuristicItem {
  heuristic: string;
  evidence: string;
  confidence: number;
}

export interface EodReview {
  review_date: string;
  created_at: string;
  summary: string;
  learned_heuristics: HeuristicItem[];
}

export interface ReportFillRequest {
  executed_price: number;
  executed_quantity: number;
  executed_at: string;
  note?: string | null;
}

interface SignalStatusResponse {
  signal_id: string;
  status: PortfolioSignalStatus;
}

// 🆕 P26: 保有銘柄の追加・更新・削除・売却。
export interface AddHoldingRequest {
  symbol: string;
  quantity: number;
  avg_cost: number;
  acquired_at: string; // YYYY-MM-DD
}

export interface SellHoldingRequest {
  quantity: number;
  sell_price: number;
  sold_at: string; // YYYY-MM-DD
  note?: string | null;
}

export interface SellHistoryEntry {
  sell_id: string;
  holding_id: string;
  symbol: string;
  company_name: string | null;
  quantity: number;
  avg_cost: number;
  sell_price: number;
  realized_pnl: number;
  sold_at: string;
  note: string | null;
}

export function fetchPortfolio(): Promise<PortfolioSummary> {
  return api.get<PortfolioSummary>('/portfolio');
}

export function addHolding(req: AddHoldingRequest): Promise<{ holding_id: string }> {
  return api.post<{ holding_id: string }>('/portfolio/holdings', req);
}

export function deleteHolding(holdingId: string): Promise<{ holding_id: string }> {
  return api.del<{ holding_id: string }>(`/portfolio/holdings/${encodeURIComponent(holdingId)}`);
}

export function sellHolding(holdingId: string, req: SellHoldingRequest): Promise<SellHistoryEntry> {
  return api.post<SellHistoryEntry>(`/portfolio/holdings/${encodeURIComponent(holdingId)}/sell`, req);
}

export function fetchSellHistory(): Promise<SellHistoryEntry[]> {
  return api.get<SellHistoryEntry[]>('/portfolio/sell-history');
}

export function fetchSignals(params?: { status?: PortfolioSignalStatus }): Promise<PortfolioSignal[]> {
  const qs = params?.status ? `?status=${encodeURIComponent(params.status)}` : '';
  return api.get<PortfolioSignal[]>(`/portfolio/signals${qs}`);
}

export function runSignalScan(): Promise<{ signal_ids: string[]; count: number }> {
  return api.post('/portfolio/signals/run');
}

export function approveSignal(signalId: string): Promise<SignalStatusResponse> {
  return api.post(`/portfolio/signals/${encodeURIComponent(signalId)}/approve`);
}

export function rejectSignal(signalId: string): Promise<SignalStatusResponse> {
  return api.post(`/portfolio/signals/${encodeURIComponent(signalId)}/reject`);
}

export function reportFill(signalId: string, req: ReportFillRequest): Promise<SignalStatusResponse> {
  return api.post(`/portfolio/signals/${encodeURIComponent(signalId)}/report-fill`, req);
}

export function fetchLatestEodReview(): Promise<EodReview | null> {
  return api.get<EodReview | null>('/portfolio/eod-review');
}

export function runEodReview(force = false): Promise<EodReview> {
  return api.post<EodReview>(`/portfolio/eod-review/run${force ? '?force=true' : ''}`);
}
