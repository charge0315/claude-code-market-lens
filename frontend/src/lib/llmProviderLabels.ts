// LLM プロバイダの表示ラベル共通ヘルパー。
//
// `challenger_version`（shadow 判定）は `"<provider_id>:<model_id>"` 形式で保存される
// （`backend/services/llm/registry.py` 参照）。複数コンポーネント（ShadowPicksBoard・
// PickDetailPanel・SignalQueue・PickedTickersList・AiPickSelector）で同じラベル変換が
// 必要なため、ここに一本化する。

const PROVIDER_LABELS: Record<string, string> = {
  anthropic: 'Claude',
  openai: 'ChatGPT',
  gemini: 'Gemini',
};

export function providerLabel(providerId: string): string {
  return PROVIDER_LABELS[providerId] ?? providerId;
}

// `challenger_version`（"gemini:gemini-2.5-pro" 等）からプロバイダ表示名を取り出す。
export function challengerProviderLabel(challengerVersion: string): string {
  const [providerId] = challengerVersion.split(':');
  return providerLabel(providerId);
}

// モデル名込みの詳細ラベル（例: "Gemini（gemini-2.5-pro）"）。
export function challengerDetailLabel(challengerVersion: string): string {
  const [providerId, ...rest] = challengerVersion.split(':');
  const model = rest.join(':');
  const label = providerLabel(providerId);
  return model ? `${label}（${model}）` : label;
}
