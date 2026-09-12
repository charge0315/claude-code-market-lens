'use client';

import { useEffect, useRef, useState, type ReactNode } from 'react';
import {
  fetchTrainingStatus,
  startTrainingBatch,
  type TrainingBatchSummary,
  type TrainingModelType,
} from '@/lib/api/registry';
import './model-lab.css';

// 銘柄別モデル（P9、xgboost/random_forest/lstm/transformer）の日次学習バッチを
// celery beat の発火を待たずに即時実行するトリガー。東証全銘柄のうち当日上限まで
// （未学習優先→最も学習が古い順）を学習し、品質ゲート合格分は自動で champion 化される
// （人手承認は不要、`per_ticker_training_service.py` 参照）。
//
// 🔧 P13h: バッチはモデルタイプにより数十秒〜数分かかりうるため、開始 API はバックグラウンド
// 起動のみ行い即座に返る。完了は `fetchTrainingStatus` を一定間隔でポーリングして確認する
// （同期 await 方式だと経路上のどこかのタイムアウトでブラウザ側に「失敗」と誤表示される
// 不整合が実機で見つかったための変更 — バックエンド自体は正常に学習・champion化を完了して
// いた）。モデルタイプごとに独立して実行できる（互いに待ち合わせない）。

const MODEL_TYPES: ReadonlyArray<{ value: TrainingModelType; label: string }> = [
  { value: 'xgboost', label: 'XGBoost' },
  { value: 'random_forest', label: 'RandomForest' },
  { value: 'lstm', label: 'LSTM' },
  { value: 'transformer', label: 'Transformer' },
];

const POLL_INTERVAL_MS = 3000;

function summaryText(s: TrainingBatchSummary): string {
  if (s.error) return `学習の実行に失敗しました: ${s.error}`;
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
  const [running, setRunning] = useState<Partial<Record<TrainingModelType, boolean>>>({});
  const [attemptedToday, setAttemptedToday] = useState<Partial<Record<TrainingModelType, number>>>({});
  const [results, setResults] = useState<Partial<Record<TrainingModelType, TrainingBatchSummary>>>({});
  const [startErrors, setStartErrors] = useState<Partial<Record<TrainingModelType, string>>>({});
  const timers = useRef<Partial<Record<TrainingModelType, ReturnType<typeof setTimeout>>>>({});

  useEffect(() => {
    const activeTimers = timers.current;
    return () => {
      Object.values(activeTimers).forEach((id) => {
        if (id) clearTimeout(id);
      });
    };
  }, []);

  const poll = (modelType: TrainingModelType): void => {
    fetchTrainingStatus(modelType)
      .then((status) => {
        setAttemptedToday((prev) => ({ ...prev, [modelType]: status.attempted_today }));
        if (status.running) {
          timers.current[modelType] = setTimeout(() => poll(modelType), POLL_INTERVAL_MS);
          return;
        }
        setRunning((prev) => ({ ...prev, [modelType]: false }));
        if (status.last_result) setResults((prev) => ({ ...prev, [modelType]: status.last_result! }));
      })
      .catch(() => {
        setRunning((prev) => ({ ...prev, [modelType]: false }));
        setStartErrors((prev) => ({ ...prev, [modelType]: '進捗の取得に失敗しました' }));
      });
  };

  const handleRun = (modelType: TrainingModelType): void => {
    setRunning((prev) => ({ ...prev, [modelType]: true }));
    setStartErrors((prev) => ({ ...prev, [modelType]: undefined }));
    startTrainingBatch(modelType)
      .then(() => poll(modelType))
      .catch(() => {
        setRunning((prev) => ({ ...prev, [modelType]: false }));
        setStartErrors((prev) => ({ ...prev, [modelType]: '学習の起動に失敗しました' }));
      });
  };

  return (
    <div className="model-lab-panel">
      <p className="model-lab-as-of">
        東証全銘柄のうち当日の学習上限まで（未学習優先→最も学習が古い順）を即時学習する。
        モデルタイプにより数十秒〜数分かかる（バックグラウンドで実行、完了まで進捗を表示する）。
        品質ゲート合格分は自動で champion 化される（人手承認は不要）。
      </p>
      <ul className="training-trigger-list">
        {MODEL_TYPES.map(({ value, label }) => {
          const isRunning = running[value] === true;
          const summary = results[value];
          const startError = startErrors[value];
          const attempted = attemptedToday[value];
          return (
            <li key={value} className="training-trigger-row">
              <span className="training-trigger-label">{label}</span>
              <button type="button" onClick={() => handleRun(value)} disabled={isRunning}>
                {isRunning ? '実行中…' : '今すぐ学習'}
              </button>
              {isRunning && typeof attempted === 'number' && (
                <span className="model-lab-brier">試行済み(本日計) {attempted}</span>
              )}
              {startError && <span className="signal-queue-error">{startError}</span>}
              {!isRunning && !startError && summary && (
                <span className={summary.error ? 'signal-queue-error' : 'model-lab-brier'}>{summaryText(summary)}</span>
              )}
            </li>
          );
        })}
      </ul>
    </div>
  );
}
