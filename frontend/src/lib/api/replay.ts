// 過去日リプレイ学習 API（`backend/routers/replay.py`、🆕 P37）の薄い型付きラッパ。

import { api } from '@/lib/api/client';

export type ReplayStatus = 'pending' | 'running' | 'stopping' | 'stopped' | 'completed' | 'failed';
export type ReplayHorizonType = 'short_term' | 'mid_term';

export interface PerformanceStats {
  n: number;
  win_rate?: number;
  avg_realized?: number;
  avg_excess?: number;
  hit_target_rate?: number;
  hit_stop_rate?: number;
}

export interface CalibrationBucket {
  bucket_low: number;
  bucket_high: number;
  n: number;
  win_rate: number;
}

export interface HorizonBlock {
  performance: PerformanceStats;
  calibration_table: CalibrationBucket[];
  factor_ics: Record<string, number | null>;
}

export interface ReplaySummary {
  horizons: Record<ReplayHorizonType, Record<string, HorizonBlock>>;
  ic_weights: Record<ReplayHorizonType, Record<string, number>>;
  calibration: Record<ReplayHorizonType, { horizon_days: number; n: number; method: string }>;
  challenger_version: string | null;
}

export interface ReplayRun {
  run_id: string;
  status: ReplayStatus;
  start_date: string;
  end_date: string;
  cursor_date: string | null;
  error: string | null;
  summary: ReplaySummary | null;
  heartbeat_at: string | null;
  created_at: string;
  is_alive: boolean;
}

export interface ReplayRetrain {
  trained_on: string;
  model_version: string;
  metrics: Record<string, number | string>;
}

export interface ReplayDetail {
  run: ReplayRun;
  pick_counts: Partial<Record<ReplayHorizonType, number>>;
  retrains: ReplayRetrain[];
  live: Record<ReplayHorizonType, { horizon_days: number; performance: PerformanceStats }>;
}

export function fetchReplayRuns(): Promise<ReplayRun[]> {
  return api.get<ReplayRun[]>('/replay/runs');
}

export function fetchReplayDetail(runId: string): Promise<ReplayDetail> {
  return api.get<ReplayDetail>(`/replay/runs/${encodeURIComponent(runId)}`);
}

export function startReplay(range: { start_date?: string; end_date?: string }): Promise<{ run_id: string }> {
  return api.post('/replay/runs', range);
}

export function stopReplay(runId: string): Promise<{ run_id: string; status: string }> {
  return api.post(`/replay/runs/${encodeURIComponent(runId)}/stop`);
}

export function resumeReplay(runId: string): Promise<{ run_id: string; status: string }> {
  return api.post(`/replay/runs/${encodeURIComponent(runId)}/resume`);
}
