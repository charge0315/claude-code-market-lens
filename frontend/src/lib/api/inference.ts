// AI 推論トレース API（`backend/routers/inference.py`）の薄い型付きラッパ。

import { api } from '@/lib/api/client';
import type { HorizonType, ShadowPrediction } from '@/lib/api/picks';
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

// 🆕 P36: 任意銘柄のオンデマンド推論トレース（`/chart` 画面から、AI ピック対象外も含む）。
// `prediction_ledger` を汚さない「試し打ち」実行 — 詳細は `backend/services/inference/sandbox.py`。

export interface SandboxTriggerResponse {
  run_id: string;
}

export function triggerSandboxInference(symbol: string, horizonType: HorizonType): Promise<SandboxTriggerResponse> {
  return api.post<SandboxTriggerResponse>('/inference/sandbox', { symbol, horizon_type: horizonType });
}

export function fetchSandboxShadow(runId: string): Promise<ShadowPrediction[]> {
  return api.get<ShadowPrediction[]>(`/inference/${encodeURIComponent(runId)}/shadow`);
}
