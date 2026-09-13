// 外部 API キー設定 API（`backend/routers/settings.py`）の薄い型付きラッパ。

import { api } from '@/lib/api/client';

export type ApiKeyField = 'anthropic_api_key' | 'gemini_api_key' | 'jquants_api_key';

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
