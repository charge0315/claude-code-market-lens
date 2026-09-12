// モデルレジストリ API（`backend/routers/registry.py`）の薄い型付きラッパ。

import { api } from '@/lib/api/client';

export interface Champion {
  lane: string;
  champion_version: string;
  promoted_at: string;
  promoted_by: string;
}

export interface Promotion {
  promotion_id: string;
  lane: string;
  challenger_version: string;
  champion_version: string | null;
  evaluated_at: string;
  holdout_delta: number;
  calib_regressed: number;
  paper_perf_delta: number;
  paper_days: number;
  verdict: 'propose_promote' | 'hold' | 'reject';
  applied: number;
  rationale: string;
}

export interface DriftSnapshot {
  drift_id: string;
  computed_at: string;
  feature_name: string;
  psi: number;
  baseline_window: string;
  current_window: string;
  drift_flag: number;
  triggered_retrain: number;
}

export function fetchChampions(): Promise<Champion[]> {
  return api.get<Champion[]>('/registry/champions');
}

export function fetchPromotions(params?: { lane?: string; limit?: number }): Promise<Promotion[]> {
  const q = new URLSearchParams();
  if (params?.lane) q.set('lane', params.lane);
  if (params?.limit) q.set('limit', String(params.limit));
  const qs = q.toString();
  return api.get<Promotion[]>(`/registry/promotions${qs ? `?${qs}` : ''}`);
}

export function applyPromotion(promotionId: string): Promise<{ promotion_id: string; applied: boolean }> {
  return api.post(`/registry/promotions/${encodeURIComponent(promotionId)}/apply`);
}

export function fetchDrift(params?: { feature?: string; limit?: number }): Promise<DriftSnapshot[]> {
  const q = new URLSearchParams();
  if (params?.feature) q.set('feature', params.feature);
  if (params?.limit) q.set('limit', String(params.limit));
  const qs = q.toString();
  return api.get<DriftSnapshot[]>(`/registry/drift${qs ? `?${qs}` : ''}`);
}

export type TrainingModelType = 'xgboost' | 'random_forest' | 'lstm' | 'transformer';

export interface TrainingBatchSummary {
  model_type: TrainingModelType;
  attempted_today: number;
  trained_this_call: number;
  failed_this_call: number;
  quota_reached: boolean;
  activated_this_call: number;
}

// 銘柄別モデル（P9）の日次学習バッチを手動実行する。モデルタイプにより数十秒〜数分かかる
// （celery beat の1firing予算と同じ時間予算で動く、`per_ticker_training_service.py` 参照）。
export function runTrainingBatch(modelType: TrainingModelType): Promise<TrainingBatchSummary> {
  return api.post<TrainingBatchSummary>('/registry/training/run', { model_type: modelType });
}
