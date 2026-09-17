'use client';

import { useEffect, useState } from 'react';
import { fetchLLMProviderSettings, type LLMFeatureId } from '@/lib/api/settings';

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

// 機能ごとの公式/シャドウ表示名。「公式」「シャドウ」という抽象語の代わりに実際のモデル名
// （Claude/Gemini/ChatGPT）を表示するため（ユーザー指示）。個々のピックが実際にどのプロバイダで
// 生成されたかは永続化していない（`PicksBoard.tsx` 参照）ので、ここでは「機能ごとに現在設定
// されているプロバイダ」を表示する近似値とする（設定変更前に生成された過去ピックとはズレうる）。
interface FeatureLabels {
  official: string;
  shadow: string[];
}

const FALLBACK_LABELS: FeatureLabels = { official: '公式', shadow: [] };

let labelsPromise: Promise<Record<LLMFeatureId, FeatureLabels>> | null = null;

function loadFeatureLabels(): Promise<Record<LLMFeatureId, FeatureLabels>> {
  if (!labelsPromise) {
    labelsPromise = fetchLLMProviderSettings()
      .then((res) => {
        const byFeature = {} as Record<LLMFeatureId, FeatureLabels>;
        for (const f of res.features) {
          byFeature[f.feature] = {
            official: providerLabel(f.primary_provider),
            shadow: f.shadow_providers.map(providerLabel),
          };
        }
        return byFeature;
      })
      .catch((err: unknown) => {
        labelsPromise = null; // 失敗時は次回呼び出しで再取得できるようにする
        throw err;
      });
  }
  return labelsPromise;
}

function useFeatureLabels(feature: LLMFeatureId): FeatureLabels {
  const [labels, setLabels] = useState(FALLBACK_LABELS);

  useEffect(() => {
    let cancelled = false;
    loadFeatureLabels()
      .then((byFeature) => {
        if (!cancelled) setLabels(byFeature[feature] ?? FALLBACK_LABELS);
      })
      .catch(() => {
        // 取得失敗時はフォールバック（「公式」）のまま表示を壊さない。
      });
    return () => {
      cancelled = true;
    };
  }, [feature]);

  return labels;
}

// 機能(feature)の「公式」表示名をモデル名（例: "Claude"）で返す。取得前・失敗時は「公式」。
export function useOfficialProviderLabel(feature: LLMFeatureId): string {
  return useFeatureLabels(feature).official;
}

// 機能(feature)の「シャドウ」表示名一覧をモデル名（例: ["Gemini"]）で返す。
export function useShadowProviderLabels(feature: LLMFeatureId): string[] {
  return useFeatureLabels(feature).shadow;
}
