// 評価指標 API（`backend/routers/eval.py`）の薄い型付きラッパ。

import { api } from '@/lib/api/client';

export type EvalScope = 'mid_term' | 'short_term' | 'combined';

export interface EvalSnapshot {
  snapshot_id: string;
  computed_at: string;
  scope: string;
  model_version: string | null;
  metric_name: string;
  metric_value: number;
  sample_n: number;
  horizon_days: number | null;
  confidence_bucket: string | null;
}

export interface CalibrationPoint {
  p_pred: number;
  p_obs: number;
  n: number;
}

export interface CalibrationCurve {
  curve_id: string;
  computed_at: string;
  scope: string;
  horizon_days: number | null;
  direction: string | null;
  points: CalibrationPoint[];
  brier: number | null;
  is_calibrated: number;
}

export interface MetricDelta {
  scope: string;
  metric: string;
  before: number;
  after: number;
  delta: number;
  before_at: string;
  after_at: string;
}

export interface WeeklyLearningSummary {
  window_days: number;
  as_of: string;
  metric_deltas: MetricDelta[];
  recent_promotions: Record<string, unknown>[];
  recent_drift_flags: Record<string, unknown>[];
}

export function fetchGrowth(params?: { scope?: EvalScope; metric?: string; limit?: number }): Promise<EvalSnapshot[]> {
  const q = new URLSearchParams();
  if (params?.scope) q.set('scope', params.scope);
  if (params?.metric) q.set('metric', params.metric);
  if (params?.limit) q.set('limit', String(params.limit));
  const qs = q.toString();
  return api.get<EvalSnapshot[]>(`/eval/growth${qs ? `?${qs}` : ''}`);
}

export function fetchCalibration(scope: EvalScope, horizon?: number): Promise<CalibrationCurve | null> {
  const q = new URLSearchParams({ scope });
  if (horizon) q.set('horizon', String(horizon));
  return api.get<CalibrationCurve | null>(`/eval/calibration?${q.toString()}`);
}

export function fetchWeeklyLearning(windowDays = 7): Promise<WeeklyLearningSummary> {
  return api.get<WeeklyLearningSummary>(`/eval/weekly-learning?window_days=${windowDays}`);
}
