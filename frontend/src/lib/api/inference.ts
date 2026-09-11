// AI 推論トレース API（`backend/routers/inference.py`）の薄い型付きラッパ。

import { api } from '@/lib/api/client';
import type { TraceEvent } from '@/lib/pipeline/types';

export interface RunSummary {
  run_id: string;
  symbol: string;
  horizon_type: string;
  status: string;
  started_at: string;
  finished_at: string | null;
  pick_id: string | null;
}

export function fetchRecentRuns(params?: { horizonType?: string; limit?: number }): Promise<RunSummary[]> {
  const q = new URLSearchParams();
  if (params?.horizonType) q.set('horizon_type', params.horizonType);
  if (params?.limit) q.set('limit', String(params.limit));
  const qs = q.toString();
  return api.get<RunSummary[]>(`/inference/runs${qs ? `?${qs}` : ''}`);
}

export function fetchReplay(runId: string): Promise<TraceEvent[]> {
  return api.get<TraceEvent[]>(`/inference/${encodeURIComponent(runId)}/replay`);
}
