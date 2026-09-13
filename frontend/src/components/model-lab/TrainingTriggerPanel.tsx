'use client';

import { useEffect, useRef, useState, type ReactNode } from 'react';
import {
  fetchModelCoverage,
  fetchTrainingStatus,
  startTrainingBatch,
  type ModelCoverage,
  type TrainingModelType,
  type TrainingStatus,
} from '@/lib/api/registry';
import './model-lab.css';

// 銘柄別モデル（P9、xgboost/random_forest/lstm/transformer）の日次学習バッチを
// celery beat の発火を待たずに即時実行するトリガー。品質ゲート合格分は自動で champion 化
// される（人手承認は不要、`per_ticker_training_service.py` 参照）。
//
// 🔧 P13h: バッチはモデルタイプにより数十秒〜数分かかりうるため、開始 API はバックグラウンド
// 起動のみ行い即座に返る。完了は `fetchTrainingStatus` を一定間隔でポーリングして確認する。
//
// 🆕 P14: 手動トリガーは「いけるところまでいく」設計。
//
// 🔧 P17: 各カードに実行中の生きた状態（処理中の銘柄・進捗率・残り推定時間・
// データソース内訳・品質ゲート通過率・最終学習日時）を表示するダッシュボード風パネルへ刷新した。
//
// 🔧 P24: 「学習を開始」ボタンは1つにまとめず、モデルタイプごとにカード内へ配置する
// （個別に開始・進捗確認できるようにする、ユーザー指示）。

interface ModelTypeInfo {
  value: TrainingModelType;
  label: string;
  /** 技術的な一言タグ（モデルの方式）。 */
  tagline: string;
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
    tagline: '勾配ブースティング木',
    description: '表形式データの学習が得意な高速AI。多くの決定木を少しずつ改善しながら組み合わせます。',
    defaults: '既定設定: 決定木100本・木の深さ5・学習率0.1',
  },
  {
    value: 'random_forest',
    label: 'RandomForest',
    tagline: '決定木のアンサンブル',
    description: '複数の判断を多数決でまとめる、安定志向のAI。',
    defaults: '既定設定: 決定木100本・木の深さ5',
  },
  {
    value: 'lstm',
    label: 'LSTM',
    tagline: '時系列を扱うRNN（長短期記憶）',
    description: '時系列の流れを記憶しながら学習するAI。過去の値動きのパターンを捉えるのが得意です。',
    defaults: '既定設定: 隠れ層64ユニット・2層構造',
  },
  {
    value: 'transformer',
    label: 'Transformer',
    tagline: '注意機構ベースのシーケンスモデル',
    description: '最新の時系列AI。値動きの中でも特に重要な期間に注目して学習します。',
    defaults: '既定設定: 64次元・2層構造',
  },
];

const POLL_INTERVAL_MS = 3000;
const COVERAGE_REFRESH_MS = 10000;

function formatEta(seconds: number | null): string {
  if (seconds === null || !Number.isFinite(seconds)) return '—';
  const totalMinutes = Math.round(seconds / 60);
  if (totalMinutes < 1) return '1分未満';
  const hours = Math.floor(totalMinutes / 60);
  const minutes = totalMinutes % 60;
  if (hours === 0) return `${minutes}分`;
  return `${hours}時間${minutes}分`;
}

function formatRelativeTime(iso: string | null): string {
  if (!iso) return '—';
  const then = new Date(iso).getTime();
  if (Number.isNaN(then)) return '—';
  const diffMinutes = Math.floor((Date.now() - then) / 60000);
  if (diffMinutes < 1) return 'たった今';
  if (diffMinutes < 60) return `${diffMinutes}分前`;
  const diffHours = Math.floor(diffMinutes / 60);
  if (diffHours < 24) return `${diffHours}時間前`;
  return `${Math.floor(diffHours / 24)}日前`;
}

function pct(numerator: number, denominator: number): number {
  return denominator > 0 ? (numerator / denominator) * 100 : 0;
}

export function TrainingTriggerPanel(): ReactNode {
  const [statuses, setStatuses] = useState<Partial<Record<TrainingModelType, TrainingStatus>>>({});
  const [coverage, setCoverage] = useState<ModelCoverage[]>([]);
  const [startErrors, setStartErrors] = useState<Partial<Record<TrainingModelType, string>>>({});
  const timers = useRef<Partial<Record<TrainingModelType, ReturnType<typeof setTimeout>>>>({});

  useEffect(() => {
    const activeTimers = timers.current;
    fetchModelCoverage()
      .then(setCoverage)
      .catch(() => {
        /* カバレッジ表示は補助情報のため、取得失敗時は静かに空のまま表示する */
      });
    const coverageInterval = setInterval(() => {
      fetchModelCoverage()
        .then(setCoverage)
        .catch(() => undefined);
    }, COVERAGE_REFRESH_MS);
    return () => {
      clearInterval(coverageInterval);
      Object.values(activeTimers).forEach((id) => {
        if (id) clearTimeout(id);
      });
    };
  }, []);

  const poll = (modelType: TrainingModelType): void => {
    fetchTrainingStatus(modelType)
      .then((status) => {
        setStatuses((prev) => ({ ...prev, [modelType]: status }));
        if (status.running) {
          timers.current[modelType] = setTimeout(() => poll(modelType), POLL_INTERVAL_MS);
          return;
        }
        fetchModelCoverage()
          .then(setCoverage)
          .catch(() => undefined);
      })
      .catch(() => {
        setStartErrors((prev) => ({ ...prev, [modelType]: '進捗の取得に失敗しました' }));
      });
  };

  const handleRun = (modelType: TrainingModelType): void => {
    setStartErrors((prev) => ({ ...prev, [modelType]: undefined }));
    startTrainingBatch(modelType)
      .then(() => poll(modelType))
      .catch(() => {
        setStartErrors((prev) => ({ ...prev, [modelType]: '学習の起動に失敗しました' }));
      });
  };

  const runningCount = MODEL_TYPES.filter(({ value }) => statuses[value]?.running).length;
  const avgCoveragePct =
    coverage.length > 0
      ? coverage.reduce((sum, c) => sum + pct(c.trained_count, c.universe_size), 0) / coverage.length
      : 0;

  const logLines = MODEL_TYPES.map(({ value, label }) => {
    const status = statuses[value];
    if (status?.running) {
      const p = status.progress;
      const ticker = p?.current_ticker ?? '…';
      return `${label}: 実行中（${ticker} を処理中、${p?.processed ?? 0}/${p?.total ?? 0}件）`;
    }
    const result = status?.last_result;
    if (result?.error) return `${label}: 前回の実行でエラーが発生しました（${result.error}）`;
    if (result) {
      return `${label}: 前回 学習${result.trained_this_call}件・失敗${result.failed_this_call}件・champion化${result.activated_this_call}件`;
    }
    return null;
  }).filter((line): line is string => line !== null);

  return (
    <div className="model-lab-panel">
      <p className="model-lab-as-of">
        モデルごとに「学習を開始」ボタンを押すと、東証の全銘柄を対象にそのAIモデルを学習します。
        「学習が済んでいない銘柄」「最も長く再学習されていない銘柄」から順に、いけるところまで自動で
        進みます。途中でページを閉じても学習は続行され、次に開いたときや再度ボタンを押したときに続きから
        再開します。
      </p>

      <div className="training-panel-header">
        <span className="model-lab-brier">
          実行中 {runningCount}/{MODEL_TYPES.length} モデル・平均カバレッジ {avgCoveragePct.toFixed(0)}%
        </span>
      </div>

      <ul className="training-trigger-list">
        {MODEL_TYPES.map(({ value, label, tagline, description, defaults }) => {
          const status = statuses[value];
          const running = status?.running ?? false;
          const progress = status?.progress ?? null;
          const row = coverage.find((c) => c.model_type === value);
          const progressPct = running && progress && progress.total > 0 ? pct(progress.processed, progress.total) : 0;
          const coveragePct = row ? pct(row.trained_count, row.universe_size) : 0;
          const yfinancePct = row ? pct(row.yfinance_count, row.universe_size) : 0;
          const jquantsPct = row ? pct(row.jquants_count, row.universe_size) : 0;
          const failedCount = running ? (progress?.failed_this_run ?? 0) : (status?.last_result?.failed_this_call ?? 0);
          const startError = startErrors[value];

          return (
            <li key={value} className="training-trigger-card">
              <div className="training-trigger-card-header">
                <div>
                  <span className="training-trigger-label">{label}</span>
                  <span className="training-trigger-tagline">{tagline}</span>
                </div>
                <span className={running ? 'training-status-badge is-running' : 'training-status-badge'}>
                  {running ? '実行中' : '待機中'}
                </span>
              </div>
              <div className="training-trigger-copy">
                <p className="training-trigger-description">{description}</p>
                <p className="training-trigger-defaults">{defaults}</p>
              </div>

              <button type="button" className="training-trigger-start-btn" onClick={() => handleRun(value)} disabled={running}>
                {running ? '実行中…' : '▶ 学習を開始'}
              </button>

              <div className="training-stat-row">
                <span className="training-stat-label">学習進捗</span>
                <span className="training-stat-value">{running ? `${progressPct.toFixed(0)}%` : '0%'}</span>
              </div>
              <span className="training-progress-bar" aria-hidden="true">
                <span className="training-progress-bar-determinate" style={{ width: `${running ? progressPct : 0}%` }} />
              </span>

              <div className="training-stat-row">
                <span className="training-stat-label">カバレッジ（データソース別）</span>
                <span className="training-stat-value">{coveragePct.toFixed(0)}%</span>
              </div>
              <span className="data-source-bar" aria-hidden="true">
                <span className="data-source-bar-yfinance" style={{ width: `${yfinancePct}%` }} />
                <span className="data-source-bar-jquants" style={{ width: `${jquantsPct}%` }} />
              </span>
              <p className="training-source-legend">
                <span>
                  <i className="training-source-swatch training-source-swatch-yfinance" />
                  yfinance {yfinancePct.toFixed(0)}%
                </span>
                <span>
                  <i className="training-source-swatch training-source-swatch-jquants" />
                  J-Quants補完 {jquantsPct.toFixed(0)}%
                </span>
              </p>

              <div className="training-stat-grid">
                <div className="training-stat">
                  <span className="training-stat-label">処理中の銘柄</span>
                  <span className="training-stat-value">{running ? (progress?.current_ticker ?? '—') : '—'}</span>
                </div>
                <div className="training-stat">
                  <span className="training-stat-label">精度スコア（既存比）</span>
                  <span className="training-stat-value">
                    {running && progress?.promotion_rate_pct !== null && progress?.promotion_rate_pct !== undefined
                      ? `${progress.promotion_rate_pct.toFixed(0)}%`
                      : '—'}
                  </span>
                </div>
                <div className="training-stat">
                  <span className="training-stat-label">残り推定時間</span>
                  <span className="training-stat-value">{running ? formatEta(progress?.eta_seconds ?? null) : '—'}</span>
                </div>
                <div className="training-stat">
                  <span className="training-stat-label">エラー・失敗件数</span>
                  <span className="training-stat-value">{failedCount}件</span>
                </div>
                <div className="training-stat">
                  <span className="training-stat-label">最終学習日時</span>
                  <span className="training-stat-value">{formatRelativeTime(row?.last_trained_at ?? null)}</span>
                </div>
              </div>

              {startError && <p className="signal-queue-error">{startError}</p>}
            </li>
          );
        })}
      </ul>

      <div className="training-run-log">
        <p className="model-lab-subheading">実行ログ</p>
        {logLines.length === 0 ? (
          <p className="model-lab-as-of">まだ実行履歴がありません。上の各モデルのボタンから学習を開始してください。</p>
        ) : (
          <ul className="training-run-log-list">
            {logLines.map((line) => (
              <li key={line}>{line}</li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}
