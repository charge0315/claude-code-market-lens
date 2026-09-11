// AI 推論トレース（P6, VZ-6/N4）の型定義。バックエンド `backend/models/inference.py` /
// `backend/services/db/inference_trace_db.py` の JSON 形状に対応する。

export type StageName = 'collect' | 'subscore' | 'synthesis' | 'llm_overlay' | 'bracket' | 'verify';
export type StageStatus = 'pending' | 'running' | 'done' | 'failed';
export type RunStatus = 'pending' | 'running' | 'done' | 'rejected' | 'failed';

// 実行順（バックエンド `models/inference.STAGE_ORDER` と一致させる。§3.1 の名目上の並びとは
// 異なり synthesis が llm_overlay より前 — 理由はバックエンド側 docstring 参照）。
export const STAGE_ORDER: readonly StageName[] = [
  'collect',
  'subscore',
  'synthesis',
  'llm_overlay',
  'bracket',
  'verify',
];

export const STAGE_LABELS: Record<StageName, string> = {
  collect: '収集',
  subscore: 'サブスコア',
  synthesis: '合成',
  llm_overlay: 'LLM深掘り',
  bracket: 'ブラケット',
  verify: '検証',
};

export interface TraceEvent {
  trace_id?: string;
  run_id: string;
  pick_id: string | null;
  symbol: string;
  horizon_type: string;
  started_at: string;
  finished_at: string | null;
  status: RunStatus;
  stage: StageName;
  stage_status: StageStatus;
  stage_seq: number;
  payload: Record<string, unknown>;
  event_at: string;
}

export interface DagSnapshot {
  run_id: string;
  symbol: string | null;
  horizon_type: string | null;
  status: RunStatus;
  started_at: string | null;
  finished_at: string | null;
  pick_id: string | null;
  stages: Record<StageName, StageStatus>;
}

export interface SourceContribution {
  weight_share: number;
  contribution: number;
  score: number;
}

export const FACTOR_LABELS: Record<string, string> = {
  technical: 'テクニカル',
  ml_prediction: 'AI予測',
  fundamental: 'ファンダメンタル',
  sentiment: 'センチメント',
};
