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
// celery beat の発火を待たずに即時実行するトリガー。品質ゲート合格分は自動で champion 化
// される（人手承認は不要、`per_ticker_training_service.py` 参照）。
//
// 🔧 P13h: バッチはモデルタイプにより数十秒〜数分かかりうるため、開始 API はバックグラウンド
// 起動のみ行い即座に返る。完了は `fetchTrainingStatus` を一定間隔でポーリングして確認する
// （同期 await 方式だと経路上のどこかのタイムアウトでブラウザ側に「失敗」と誤表示される
// 不整合が実機で見つかったための変更 — バックエンド自体は正常に学習・champion化を完了して
// いた）。モデルタイプごとに独立して実行できる（互いに待ち合わせない）。
//
// 🆕 P14: 手動トリガーは「いけるところまでいく」設計になった
// （`per_ticker_training_service.manual_full_run_overrides`、ユーザー確認済み）ため、
// 初心者にも「全銘柄を対象に、中断しても再開できる」ことが伝わるよう案内文を整理し、
// モデルタイプごとの平易な説明・既定のハイパーパラメータを表示する。

interface ModelTypeInfo {
  value: TrainingModelType;
  label: string;
  /** 専門用語を避けた一言説明。 */
  description: string;
  /**
   * 実際の既定ハイパーパラメータを平易に表示する（静的テキスト）。
   * 正の情報源: `backend/services/learning/per_ticker_predictor.py`
   * （XGBoostPredictor/RandomForestPredictor）・`backend/services/learning/dl/{lstm,transformer}.py`。
   * ここは表示専用で値を変更する機能ではないため、コードの既定値を変えたときは
   * このテキストも合わせて更新すること。
   */
  defaults: string;
}

const MODEL_TYPES: ReadonlyArray<ModelTypeInfo> = [
  {
    value: 'xgboost',
    label: 'XGBoost',
    description: '表形式データの学習が得意な高速AI。多くの決定木を少しずつ改善しながら組み合わせます。',
    defaults: '既定設定: 決定木100本・木の深さ5・学習率0.1',
  },
  {
    value: 'random_forest',
    label: 'RandomForest',
    description: '複数の判断を多数決でまとめる、安定志向のAI。',
    defaults: '既定設定: 決定木100本・木の深さ5',
  },
  {
    value: 'lstm',
    label: 'LSTM',
    description: '時系列の流れを記憶しながら学習するAI。過去の値動きのパターンを捉えるのが得意です。',
    defaults: '既定設定: 隠れ層64ユニット・2層構造',
  },
  {
    value: 'transformer',
    label: 'Transformer',
    description: '最新の時系列AI。値動きの中でも特に重要な期間に注目して学習します。',
    defaults: '既定設定: 64次元・2層構造',
  },
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
        ボタンを押すと、東証の全銘柄を対象に「学習が済んでいない銘柄」「最も長く再学習
        されていない銘柄」から順に、いけるところまで自動で学習します。時間がかかる場合が
        ありますが、途中でページを閉じても学習は続行され、次に開いたときや再度ボタンを
        押したときに続きから再開します。
      </p>
      <ul className="training-trigger-list">
        {MODEL_TYPES.map(({ value, label, description, defaults }) => {
          const isRunning = running[value] === true;
          const summary = results[value];
          const startError = startErrors[value];
          const attempted = attemptedToday[value];
          return (
            <li key={value} className="training-trigger-card">
              <div className="training-trigger-card-header">
                <span className="training-trigger-label">{label}</span>
                <button type="button" onClick={() => handleRun(value)} disabled={isRunning}>
                  {isRunning ? '実行中…' : '今すぐ学習'}
                </button>
              </div>
              <p className="training-trigger-description">{description}</p>
              <p className="training-trigger-defaults">{defaults}</p>
              {isRunning && (
                <div className="training-progress">
                  <span className="training-progress-bar" aria-hidden="true">
                    <span className="training-progress-bar-fill" />
                  </span>
                  {typeof attempted === 'number' && (
                    <span className="model-lab-brier">試行済み(本日計) {attempted}銘柄</span>
                  )}
                </div>
              )}
              {startError && <p className="signal-queue-error">{startError}</p>}
              {!isRunning && !startError && summary && (
                <p className={summary.error ? 'signal-queue-error' : 'model-lab-brier'}>{summaryText(summary)}</p>
              )}
            </li>
          );
        })}
      </ul>
    </div>
  );
}
