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

// モデル選択 `<select>` の「その他（手入力）」を表す番兵値（実在のモデル名と衝突しない形）。
const CUSTOM_MODEL_VALUE = '__custom__';

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
  // 「その他（手入力）」を選んだモデル欄（`${feature}-${provider}`）。プリセット値のままでも手入力へ切り替えられるよう保持する。
  const [customModelFields, setCustomModelFields] = useState<string[]>([]);

  useEffect(() => {
    fetchLLMProviderSettings()
      .then((res) => {
        setFeatures(res.features);
        setProviders(res.available_providers);
      })
      .catch(() => setError('LLMプロバイダ設定の取得に失敗しました'));
  }, []);

  const draftFor = (f: FeatureProviderSetting): FeatureProviderSetting => drafts[f.feature] ?? f;

  const modelsEqual = (a: Record<LLMProviderId, string>, b: Record<LLMProviderId, string>): boolean =>
    (Object.keys(a) as LLMProviderId[]).every((provider) => a[provider] === b[provider]);

  const isDirty = (f: FeatureProviderSetting): boolean => {
    const draft = drafts[f.feature];
    if (!draft) return false;
    return (
      draft.primary_provider !== f.primary_provider ||
      draft.shadow_providers.join(',') !== f.shadow_providers.join(',') ||
      !modelsEqual(draft.models, f.models)
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
      models: draft.models,
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
  const providerPresets = (value: LLMProviderId): string[] => providers.find((p) => p.value === value)?.model_presets ?? [];
  const presetsFromApi = (value: LLMProviderId): boolean => providers.find((p) => p.value === value)?.model_source === 'api';

  const setModel = (feature: FeatureProviderSetting, draft: FeatureProviderSetting, provider: LLMProviderId, model: string): void => {
    setDrafts((prev) => ({
      ...prev,
      [feature.feature]: { ...draft, models: { ...draft.models, [provider]: model } },
    }));
  };

  // `<datalist>` は入力中の値で候補を絞り込むため、現在値が入っていると他のプリセットが
  // 表示されなかった。常に全候補を出せる `<select>` にし、プリセット外は「その他」で手入力する。
  const renderModelField = (feature: FeatureProviderSetting, draft: FeatureProviderSetting, provider: LLMProviderId): ReactNode => {
    const fieldKey = `${feature.feature}-${provider}`;
    const current = draft.models[provider] ?? '';
    const presets = providerPresets(provider);
    const isCustom = customModelFields.includes(fieldKey) || (current !== '' && !presets.includes(current));
    return (
      <div className="llm-provider-model-field">
        <label htmlFor={`model-${fieldKey}`} className="llm-provider-model-label">
          {providerLabel(provider)} の使用モデル
        </label>
        <select
          id={`model-${fieldKey}`}
          className="llm-provider-select"
          value={isCustom ? CUSTOM_MODEL_VALUE : current}
          onChange={(e) => {
            if (e.target.value === CUSTOM_MODEL_VALUE) {
              setCustomModelFields((prev) => (prev.includes(fieldKey) ? prev : [...prev, fieldKey]));
              return;
            }
            setCustomModelFields((prev) => prev.filter((k) => k !== fieldKey));
            setModel(feature, draft, provider, e.target.value);
          }}
        >
          {presets.map((preset) => (
            <option key={preset} value={preset}>
              {preset}
            </option>
          ))}
          <option value={CUSTOM_MODEL_VALUE}>その他（手入力）</option>
        </select>
        <span className="llm-provider-model-source">
          {presetsFromApi(provider)
            ? `公式APIから取得した${presets.length}件`
            : '固定候補（APIキー未設定または一覧取得に失敗）'}
        </span>
        {isCustom && (
          <>
            <label htmlFor={`model-custom-${fieldKey}`} className="llm-provider-model-label">
              {providerLabel(provider)} のモデル名（手入力）
            </label>
            <input
              id={`model-custom-${fieldKey}`}
              type="text"
              className="llm-provider-model-input"
              value={current}
              onChange={(e) => setModel(feature, draft, provider, e.target.value)}
            />
          </>
        )}
      </div>
    );
  };

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
                {renderModelField(f, draft, draft.primary_provider)}
              </div>

              <div className="llm-provider-field">
                <span className="llm-provider-field-label">シャドウプロバイダ（比較表示のみ・複数併用可）</span>
                <div className="llm-provider-checkbox-group">
                  {providers
                    .filter((p) => p.value !== draft.primary_provider)
                    .map((p) => (
                      <div key={p.value} className="llm-provider-shadow-row">
                        <label className="llm-provider-checkbox">
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
                        {draft.shadow_providers.includes(p.value) && renderModelField(f, draft, p.value)}
                      </div>
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
