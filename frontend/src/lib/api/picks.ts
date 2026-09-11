// AI 銘柄ピック API（`backend/routers/picks.py`）の薄い型付きラッパ。

import { api } from '@/lib/api/client';

export type HorizonType = 'mid_term' | 'short_term';
export type Direction = 'bullish' | 'bearish' | 'neutral';
export type ConfidenceBucket = 'high' | 'mid' | 'low';

export interface PickSummary {
  pick_id: string;
  issued_at: string;
  horizon_type: HorizonType;
  symbol: string;
  direction: Direction;
  entry: number;
  stop: number;
  target: number;
  composite_score: number;
  concordance: number;
  confidence: number;
  confidence_bucket: ConfidenceBucket;
  rationale_text: string;
  model_version: string;
  source_contributions: Record<string, unknown>;
}

export interface RejectedPick {
  symbol: string;
  status: string;
  reason: string;
}

export interface PickRunResult {
  run_id: string;
  horizon_type: HorizonType;
  issued_at: string;
  status: 'ok' | 'empty' | 'not_configured' | 'error';
  picks: PickSummary[];
  rejected: RejectedPick[];
  message: string | null;
}

export function fetchPicks(
  horizonType: HorizonType,
  params?: { date?: string; bucket?: ConfidenceBucket; limit?: number },
): Promise<PickSummary[]> {
  const path = horizonType === 'mid_term' ? '/picks/mid-term' : '/picks/short-term';
  const q = new URLSearchParams();
  if (params?.date) q.set('date', params.date);
  if (params?.bucket) q.set('bucket', params.bucket);
  if (params?.limit) q.set('limit', String(params.limit));
  const qs = q.toString();
  return api.get<PickSummary[]>(`${path}${qs ? `?${qs}` : ''}`);
}

export function runPicks(horizonType: HorizonType): Promise<PickRunResult> {
  return api.post<PickRunResult>('/picks/run', { horizon_type: horizonType });
}
