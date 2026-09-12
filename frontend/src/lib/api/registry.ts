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
  error: string | null;
}

export interface TrainingRunAck {
  model_type: TrainingModelType;
  status: 'started' | 'already_running';
}

export interface TrainingStatus {
  model_type: TrainingModelType;
  running: boolean;
  attempted_today: number;
  last_result: TrainingBatchSummary | null;
}

// 銘柄別モデル（P9）の日次学習バッチをバックグラウンドで起動する（🔧 P13h）。
// モデルタイプにより数十秒〜数分かかりうる（celery beat の1firing予算と同じ時間予算で動く、
// `per_ticker_training_service.py` 参照）ため、リクエストは即座に返り、完了は
// `fetchTrainingStatus` をポーリングして確認する（同期 await だと経路上のタイムアウトで
// ブラウザ側に失敗と誤表示されるため、この方式へ変更した）。
export function startTrainingBatch(modelType: TrainingModelType): Promise<TrainingRunAck> {
  return api.post<TrainingRunAck>('/registry/training/run', { model_type: modelType });
}

export function fetchTrainingStatus(modelType: TrainingModelType): Promise<TrainingStatus> {
  return api.get<TrainingStatus>(`/registry/training/status?model_type=${modelType}`);
}
