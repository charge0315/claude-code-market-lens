'use client';

import { useEffect, useState, type ReactNode } from 'react';
import { fetchApiKeyStatus, updateApiKeys, type ApiKeyField, type ApiKeyStatus } from '@/lib/api/settings';
import './settings.css';

// 外部 API キー（Anthropic / Gemini / J-Quants）の設定画面（🆕 P20）。
//
// 生値はサーバから一切返さない（末尾4文字のみのマスク表示）。保存は `.env` への
// 永続化のみで、実行中の backend / celery worker・beat には反映されない
// （`backend.config.settings` は起動時に一度だけ読み込む frozen 設定のため）。
// そのため保存後は必ず再起動が必要な旨を表示する。

export function ApiKeysPanel(): ReactNode {
  const [keys, setKeys] = useState<ApiKeyStatus[]>([]);
  const [drafts, setDrafts] = useState<Partial<Record<ApiKeyField, string>>>({});
  const [revealed, setRevealed] = useState<Partial<Record<ApiKeyField, boolean>>>({});
  const [savingKey, setSavingKey] = useState<ApiKeyField | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [restartRequired, setRestartRequired] = useState(false);

  useEffect(() => {
    fetchApiKeyStatus()
      .then((res) => setKeys(res.keys))
      .catch(() => setError('設定状況の取得に失敗しました'));
  }, []);

  const handleSave = (field: ApiKeyField): void => {
    const value = drafts[field]?.trim();
    if (!value) return;
    setError(null);
    setSavingKey(field);
    updateApiKeys({ [field]: value })
      .then((res) => {
        setKeys(res.keys);
        setRestartRequired(res.restart_required);
        setDrafts((prev) => ({ ...prev, [field]: '' }));
      })
      .catch(() => setError('APIキーの更新に失敗しました'))
      .finally(() => setSavingKey(null));
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
        {keys.map((k) => (
          <li key={k.key} className="api-keys-row">
            <div className="api-keys-row-header">
              <span className="api-keys-label">{k.label}</span>
              <span className={k.configured ? 'api-keys-tag api-keys-tag-ok' : 'api-keys-tag api-keys-tag-empty'}>
                {k.configured ? `設定済み（${k.masked_value}）` : '未設定'}
              </span>
            </div>
            <div className="api-keys-row-form">
              <input
                type={revealed[k.key] ? 'text' : 'password'}
                className="api-keys-input"
                placeholder={k.configured ? '新しい値を入力すると置き換わります' : 'APIキーを入力'}
                value={drafts[k.key] ?? ''}
                autoComplete="off"
                onChange={(e) => setDrafts((prev) => ({ ...prev, [k.key]: e.target.value }))}
              />
              <button
                type="button"
                className="api-keys-reveal-btn"
                onClick={() => setRevealed((prev) => ({ ...prev, [k.key]: !prev[k.key] }))}
              >
                {revealed[k.key] ? '隠す' : '表示'}
              </button>
              <button
                type="button"
                onClick={() => handleSave(k.key)}
                disabled={!drafts[k.key]?.trim() || savingKey === k.key}
              >
                {savingKey === k.key ? '保存中…' : '保存'}
              </button>
            </div>
          </li>
        ))}
      </ul>
    </div>
  );
}
