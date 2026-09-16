'use client';

import { useEffect, useState, type ReactNode } from 'react';
import {
  fetchLLMProviderSettings,
  updateLLMProviderSetting,
  type FeatureProviderSetting,
  type LLMFeatureId,
  type LLMProviderId,
  type LLMProviderOption,
} from '@/lib/api/settings';
import './settings.css';

// 機能ごとのLLMプロバイダ選択（🆕）。
//
// 「公式」= 実際の売買判定・ピック確定を左右するプロバイダ（単一選択）。
// 「シャドウ」= 公式と同一のプロンプトを並行判定させ比較表示するだけのチャレンジャー
// （複数併用可、判定フローには一切影響しない）。保存は `.env` への永続化のみで、
// 反映には backend / celery worker・beat の再起動が必要（APIキー設定と同じ方式）。

function toggleProvider(list: LLMProviderId[], provider: LLMProviderId): LLMProviderId[] {
  return list.includes(provider) ? list.filter((p) => p !== provider) : [...list, provider];
}

export function LLMProviderPanel(): ReactNode {
  const [features, setFeatures] = useState<FeatureProviderSetting[]>([]);
  const [providers, setProviders] = useState<LLMProviderOption[]>([]);
  const [drafts, setDrafts] = useState<Partial<Record<LLMFeatureId, FeatureProviderSetting>>>({});
  const [savingFeature, setSavingFeature] = useState<LLMFeatureId | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [restartRequired, setRestartRequired] = useState(false);

  useEffect(() => {
    fetchLLMProviderSettings()
      .then((res) => {
        setFeatures(res.features);
        setProviders(res.available_providers);
      })
      .catch(() => setError('LLMプロバイダ設定の取得に失敗しました'));
  }, []);

  const draftFor = (f: FeatureProviderSetting): FeatureProviderSetting => drafts[f.feature] ?? f;

  const isDirty = (f: FeatureProviderSetting): boolean => {
    const draft = drafts[f.feature];
    if (!draft) return false;
    return (
      draft.primary_provider !== f.primary_provider ||
      draft.shadow_providers.join(',') !== f.shadow_providers.join(',')
    );
  };

  const handleSave = (feature: FeatureProviderSetting): void => {
    const draft = draftFor(feature);
    setError(null);
    setSavingFeature(feature.feature);
    updateLLMProviderSetting({
      feature: feature.feature,
      primary_provider: draft.primary_provider,
      shadow_providers: draft.shadow_providers,
    })
      .then((res) => {
        setFeatures(res.features);
        setRestartRequired(res.restart_required);
        setDrafts((prev) => {
          const next = { ...prev };
          delete next[feature.feature];
          return next;
        });
      })
      .catch(() => setError('LLMプロバイダ設定の更新に失敗しました'))
      .finally(() => setSavingFeature(null));
  };

  const providerLabel = (value: LLMProviderId): string => providers.find((p) => p.value === value)?.label ?? value;
  const providerConfigured = (value: LLMProviderId): boolean =>
    providers.find((p) => p.value === value)?.configured ?? false;

  return (
    <div className="api-keys-panel">
      {error && <p className="signal-queue-error">{error}</p>}
      {restartRequired && (
        <p className="api-keys-restart-notice">
          保存しました。変更を反映するには backend（uvicorn）と celery worker / beat の再起動が必要です。
        </p>
      )}

      <ul className="api-keys-list">
        {features.map((f) => {
          const draft = draftFor(f);
          return (
            <li key={f.feature} className="api-keys-row">
              <div className="api-keys-row-header">
                <span className="api-keys-label">{f.label}</span>
              </div>

              <div className="llm-provider-field">
                <label htmlFor={`primary-${f.feature}`} className="llm-provider-field-label">
                  公式プロバイダ（判定を左右する）
                </label>
                <select
                  id={`primary-${f.feature}`}
                  className="llm-provider-select"
                  value={draft.primary_provider}
                  onChange={(e) =>
                    setDrafts((prev) => ({
                      ...prev,
                      [f.feature]: { ...draft, primary_provider: e.target.value as LLMProviderId },
                    }))
                  }
                >
                  {providers.map((p) => (
                    <option key={p.value} value={p.value}>
                      {p.label}
                      {p.configured ? '' : '（APIキー未設定）'}
                    </option>
                  ))}
                </select>
                {!providerConfigured(draft.primary_provider) && (
                  <span className="llm-provider-warning">
                    {providerLabel(draft.primary_provider)} の API キーが未設定のため、この機能は動作しません。
                  </span>
                )}
              </div>

              <div className="llm-provider-field">
                <span className="llm-provider-field-label">シャドウプロバイダ（比較表示のみ・複数併用可）</span>
                <div className="llm-provider-checkbox-group">
                  {providers
                    .filter((p) => p.value !== draft.primary_provider)
                    .map((p) => (
                      <label key={p.value} className="llm-provider-checkbox">
                        <input
                          type="checkbox"
                          checked={draft.shadow_providers.includes(p.value)}
                          onChange={() =>
                            setDrafts((prevState) => ({
                              ...prevState,
                              [f.feature]: {
                                ...draft,
                                shadow_providers: toggleProvider(draft.shadow_providers, p.value),
                              },
                            }))
                          }
                        />
                        {p.label}
                        {!p.configured && <span className="llm-provider-warning-inline">未設定</span>}
                      </label>
                    ))}
                </div>
              </div>

              <div className="api-keys-row-form">
                <button
                  type="button"
                  onClick={() => handleSave(f)}
                  disabled={!isDirty(f) || savingFeature === f.feature}
                >
                  {savingFeature === f.feature ? '保存中…' : '保存'}
                </button>
              </div>
            </li>
          );
        })}
      </ul>
    </div>
  );
}
