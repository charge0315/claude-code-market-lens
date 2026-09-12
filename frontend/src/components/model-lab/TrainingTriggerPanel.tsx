'use client';

import { useState, type ReactNode } from 'react';
import { runTrainingBatch, type TrainingBatchSummary, type TrainingModelType } from '@/lib/api/registry';
import './model-lab.css';

// 銘柄別モデル（P9、xgboost/random_forest/lstm/transformer）の日次学習バッチを
// celery beat の発火を待たずに即時実行するトリガー。東証全銘柄のうち当日上限まで
// （未学習優先→最も学習が古い順）を学習し、品質ゲート合格分は自動で champion 化される
// （人手承認は不要、`per_ticker_training_service.py` 参照）。

const MODEL_TYPES: ReadonlyArray<{ value: TrainingModelType; label: string }> = [
  { value: 'xgboost', label: 'XGBoost' },
  { value: 'random_forest', label: 'RandomForest' },
  { value: 'lstm', label: 'LSTM' },
  { value: 'transformer', label: 'Transformer' },
];

function summaryText(s: TrainingBatchSummary): string {
  const parts = [
    `試行済み(本日計) ${s.attempted_today}`,
    `今回学習 ${s.trained_this_call}`,
    `失敗 ${s.failed_this_call}`,
    `champion化 ${s.activated_this_call}`,
  ];
  if (s.quota_reached) parts.push('上限到達');
  return parts.join(' / ');
}

export function TrainingTriggerPanel(): ReactNode {
  const [running, setRunning] = useState<TrainingModelType | null>(null);
  const [results, setResults] = useState<Partial<Record<TrainingModelType, TrainingBatchSummary>>>({});
  const [errors, setErrors] = useState<Partial<Record<TrainingModelType, string>>>({});

  const handleRun = (modelType: TrainingModelType): void => {
    setRunning(modelType);
    setErrors((prev) => ({ ...prev, [modelType]: undefined }));
    runTrainingBatch(modelType)
      .then((summary) => setResults((prev) => ({ ...prev, [modelType]: summary })))
      .catch(() => setErrors((prev) => ({ ...prev, [modelType]: '学習の実行に失敗しました' })))
      .finally(() => setRunning(null));
  };

  return (
    <div className="model-lab-panel">
      <p className="model-lab-as-of">
        東証全銘柄のうち当日の学習上限まで（未学習優先→最も学習が古い順）を即時学習する。
        モデルタイプにより数十秒〜数分かかる。品質ゲート合格分は自動で champion 化される
        （人手承認は不要）。
      </p>
      <ul className="training-trigger-list">
        {MODEL_TYPES.map(({ value, label }) => {
          const summary = results[value];
          const error = errors[value];
          return (
            <li key={value} className="training-trigger-row">
              <span className="training-trigger-label">{label}</span>
              <button type="button" onClick={() => handleRun(value)} disabled={running !== null}>
                {running === value ? '実行中…' : '今すぐ学習'}
              </button>
              {error && <span className="signal-queue-error">{error}</span>}
              {!error && summary && <span className="model-lab-brier">{summaryText(summary)}</span>}
            </li>
          );
        })}
      </ul>
    </div>
  );
}
