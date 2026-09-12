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
  company_name: string | null;
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

export interface SubScores {
  technical: number;
  trend: number;
  fundamental: number;
  sentiment: number;
}

// 🆕 P12: Gemini 等 challenger LLM の比較用判定（`shadow_predictions`）。表示専用で、
// 昇格・確度較正には一切関与しない。
export interface ShadowPrediction {
  shadow_id: string;
  challenger_version: string;
  direction: Direction;
  entry: number;
  stop: number;
  target: number;
  confidence: number;
  reasoning: string | null;
  risk_factors: string[];
  holding_period_days: number | null;
  issued_at: string;
}

export interface PickDetail {
  pick_id: string;
  run_id: string;
  issued_at: string;
  horizon_type: HorizonType;
  symbol: string;
  company_name: string | null;
  direction: Direction;
  entry: number;
  stop: number;
  target: number;
  sub_scores: SubScores;
  composite_score: number;
  concordance: number;
  confidence_raw: number;
  confidence: number;
  confidence_bucket: ConfidenceBucket;
  rationale_struct: Record<string, unknown>;
  rationale_text: string;
  model_version: string;
  source_contributions: Record<string, unknown>;
  created_at: string;
  shadow_predictions: ShadowPrediction[];
}

export function fetchPickDetail(pickId: string): Promise<PickDetail> {
  return api.get<PickDetail>(`/picks/${encodeURIComponent(pickId)}`);
}
