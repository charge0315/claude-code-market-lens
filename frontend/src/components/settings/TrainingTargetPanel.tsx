'use client';

import { useEffect, useState, type ReactNode } from 'react';
import { TickerPickerDialog } from '@/components/settings/TickerPickerDialog';
import {
  fetchTrainingTargetSettings,
  fetchTrainingTargetTickers,
  updateTrainingTargetSettings,
  type TrainingTargetMode,
  type TrainingTargetSettings,
  type TrainingTargetTicker,
} from '@/lib/api/registry';
import './settings.css';

// 学習対象設定（🆕）: 継続学習パイプラインの候補選定を絞り込むモードと、CPU負荷対策の
// 並列学習プロセス数上限。DB保存のため保存後は即座に反映される（`.env` 方式と異なり再起動不要）。

const MODE_LABELS: Record<TrainingTargetMode, string> = {
  portfolio: 'ポートフォリオにあるもの',
  picked: 'ピックした銘柄（直近30日累積）',
  all: '全銘柄',
  custom: '学習対象銘柄リスト（カスタム）',
};

const MIN_WORKERS = 1;
const MAX_WORKERS = 16;

export function TrainingTargetPanel(): ReactNode {
  const [settings, setSettings] = useState<TrainingTargetSettings | null>(null);
  const [draft, setDraft] = useState<TrainingTargetSettings | null>(null);
  const [customTickers, setCustomTickers] = useState<TrainingTargetTicker[]>([]);
  const [dialogOpen, setDialogOpen] = useState(false);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const loadCustomTickers = (): void => {
    fetchTrainingTargetTickers()
      .then(setCustomTickers)
      .catch(() => setError('学習対象銘柄リストの取得に失敗しました'));
  };

  useEffect(() => {
    fetchTrainingTargetSettings()
      .then((res) => {
        setSettings(res);
        setDraft(res);
      })
      .catch(() => setError('学習対象設定の取得に失敗しました'));
    loadCustomTickers();
  }, []);

  const isDirty =
    settings !== null &&
    draft !== null &&
    (draft.target_mode !== settings.target_mode || draft.max_parallel_workers !== settings.max_parallel_workers);

  const handleSave = (): void => {
    if (!draft) return;
    setSaving(true);
    setError(null);
    setSaved(false);
    updateTrainingTargetSettings({ target_mode: draft.target_mode, max_parallel_workers: draft.max_parallel_workers })
      .then((res) => {
        setSettings(res);
        setDraft(res);
        setSaved(true);
      })
      .catch(() => setError('学習対象設定の更新に失敗しました'))
      .finally(() => setSaving(false));
  };

  const setWorkers = (value: number): void => {
    if (!draft) return;
    setDraft({ ...draft, max_parallel_workers: Math.min(MAX_WORKERS, Math.max(MIN_WORKERS, value)) });
  };

  return (
    <div className="training-target-panel">
      {error && <p className="signal-queue-error">{error}</p>}
      {saved && (
        <p className="api-keys-restart-notice">保存しました。次回の学習バッチから即座に反映されます（再起動不要）。</p>
      )}

      {draft && (
        <>
          <fieldset className="training-target-modes">
            <legend className="llm-provider-field-label">学習対象</legend>
            {(Object.keys(MODE_LABELS) as TrainingTargetMode[]).map((mode) => (
              <label key={mode} className="llm-provider-checkbox training-target-mode-option">
                <input
                  type="radio"
                  name="training-target-mode"
                  value={mode}
                  checked={draft.target_mode === mode}
                  onChange={() => setDraft({ ...draft, target_mode: mode })}
                />
                {MODE_LABELS[mode]}
              </label>
            ))}
          </fieldset>

          {draft.target_mode === 'custom' && (
            <div className="training-target-custom-list">
              <p className="training-target-custom-count">現在 {customTickers.length} 銘柄が登録されています。</p>
              <button type="button" onClick={() => setDialogOpen(true)}>
                カスタムリストを編集
              </button>
            </div>
          )}

          <div className="llm-provider-field">
            <label htmlFor="max-parallel-workers" className="llm-provider-field-label">
              並列学習プロセス数の上限（デフォルト4）
            </label>
            <input
              id="max-parallel-workers"
              type="number"
              min={MIN_WORKERS}
              max={MAX_WORKERS}
              value={draft.max_parallel_workers}
              onChange={(e) => setWorkers(Number(e.target.value) || MIN_WORKERS)}
              className="llm-provider-model-input training-target-workers-input"
            />
            <span className="training-target-workers-hint">
              CPU負荷が高いため、通常は4以下を推奨します（{MIN_WORKERS}〜{MAX_WORKERS}）。
            </span>
          </div>

          <div className="api-keys-row-form">
            <button type="button" onClick={handleSave} disabled={!isDirty || saving}>
              {saving ? '保存中…' : '保存'}
            </button>
          </div>

          {dialogOpen && <TickerPickerDialog onClose={() => setDialogOpen(false)} onSaved={loadCustomTickers} />}
        </>
      )}
    </div>
  );
}
