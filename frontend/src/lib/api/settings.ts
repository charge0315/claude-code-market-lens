// 外部 API キー設定 / LLM プロバイダ選択 API（`backend/routers/settings.py`）の薄い型付きラッパ。

import { api } from '@/lib/api/client';

export type ApiKeyField = 'anthropic_api_key' | 'openai_api_key' | 'gemini_api_key' | 'jquants_api_key';

export interface ApiKeyStatus {
  key: ApiKeyField;
  label: string;
  configured: boolean;
  masked_value: string | null;
}

export interface ApiKeysResponse {
  keys: ApiKeyStatus[];
  restart_required: boolean;
}

export type ApiKeysUpdate = Partial<Record<ApiKeyField, string>>;

export function fetchApiKeyStatus(): Promise<ApiKeysResponse> {
  return api.get<ApiKeysResponse>('/settings/api-keys');
}

export function updateApiKeys(updates: ApiKeysUpdate): Promise<ApiKeysResponse> {
  return api.patch<ApiKeysResponse>('/settings/api-keys', updates);
}

// 機能ごとのLLMプロバイダ選択（🆕）。公式（決定を左右する）プロバイダと、シャドウ（比較用
// チャレンジャー、複数併用可）プロバイダを個別に設定できる。反映には再起動が必要（api-keysと同じ）。

export type LLMFeatureId = 'stock_pick' | 'portfolio_signal' | 'eod_review' | 'trend_analyzer';
export type LLMProviderId = 'anthropic' | 'openai' | 'gemini';

export interface LLMProviderOption {
  value: LLMProviderId;
  label: string;
  configured: boolean;
  default_model: string;
  // モデル選択の候補。model_source が 'api' なら公式モデル一覧APIの取得結果、'preset' なら固定候補
  // （APIキー未設定・取得失敗時のフォールバック）。
  model_presets: string[];
  model_source: 'api' | 'preset';
}

export interface FeatureProviderSetting {
  feature: LLMFeatureId;
  label: string;
  primary_provider: LLMProviderId;
  shadow_providers: LLMProviderId[];
  // プロバイダごとに実際に使われるモデル（機能×プロバイダの個別上書き、無ければプロバイダ既定値）。
  models: Record<LLMProviderId, string>;
}

export interface LLMProviderSettingsResponse {
  features: FeatureProviderSetting[];
  available_providers: LLMProviderOption[];
  restart_required: boolean;
}

export interface LLMProviderUpdate {
  feature: LLMFeatureId;
  primary_provider?: LLMProviderId;
  shadow_providers?: LLMProviderId[];
  // 変更したいプロバイダぶんのみ含める。空文字を指定するとプロバイダの既定モデルへ戻る。
  models?: Partial<Record<LLMProviderId, string>>;
}

export function fetchLLMProviderSettings(): Promise<LLMProviderSettingsResponse> {
  return api.get<LLMProviderSettingsResponse>('/settings/llm-providers');
}

export function updateLLMProviderSetting(update: LLMProviderUpdate): Promise<LLMProviderSettingsResponse> {
  return api.patch<LLMProviderSettingsResponse>('/settings/llm-providers', update);
}
