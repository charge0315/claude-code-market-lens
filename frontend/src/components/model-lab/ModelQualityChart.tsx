'use client';

import { useEffect, useState, type ReactNode } from 'react';
import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';
import { fetchQualityDistribution, type QualityDistribution, type TrainingModelType } from '@/lib/api/registry';
import './model-lab.css';

// モデル品質の分布（🆕 P15）: 現行 champion の skill/rmse スコアのヒストグラム。
// ビン分けはこのコンポーネント内で完結させる（YAGNI、他所からの再利用は見込まない）。

const MODEL_TYPES: ReadonlyArray<TrainingModelType> = ['xgboost', 'random_forest', 'lstm', 'transformer'];
const MODEL_TYPE_LABELS: Record<TrainingModelType, string> = {
  xgboost: 'XGBoost',
  random_forest: 'RandomForest',
  lstm: 'LSTM',
  transformer: 'Transformer',
};

type Metric = 'skill' | 'rmse';
const METRICS: ReadonlyArray<{ value: Metric; label: string }> = [
  { value: 'skill', label: 'skillスコア' },
  { value: 'rmse', label: 'RMSE' },
];

const BIN_COUNT = 10;

interface HistogramBin {
  range: string;
  count: number;
}

function buildHistogram(values: number[]): HistogramBin[] {
  if (values.length === 0) return [];
  const min = Math.min(...values);
  const max = Math.max(...values);
  if (min === max) {
    return [{ range: min.toFixed(3), count: values.length }];
  }
  const width = (max - min) / BIN_COUNT;
  const counts = new Array(BIN_COUNT).fill(0) as number[];
  for (const v of values) {
    const idx = Math.min(BIN_COUNT - 1, Math.floor((v - min) / width));
    counts[idx] += 1;
  }
  return counts.map((count, i) => ({
    range: `${(min + i * width).toFixed(2)}〜${(min + (i + 1) * width).toFixed(2)}`,
    count,
  }));
}

export function ModelQualityChart(): ReactNode {
  const [modelType, setModelType] = useState<TrainingModelType>('xgboost');
  const [metric, setMetric] = useState<Metric>('skill');
  const [distributions, setDistributions] = useState<QualityDistribution[]>([]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetchQualityDistribution()
      .then(setDistributions)
      .catch(() => setError('モデル品質分布の取得に失敗しました'));
  }, []);

  const selected = distributions.find((d) => d.model_type === modelType);
  const values = metric === 'skill' ? (selected?.skill_scores ?? []) : (selected?.rmse_scores ?? []);
  const bins = buildHistogram(values);

  return (
    <div className="model-lab-panel">
      <div className="model-lab-toolbar">
        <label className="model-lab-select">
          モデルタイプ
          <select value={modelType} onChange={(e) => setModelType(e.target.value as TrainingModelType)}>
            {MODEL_TYPES.map((mt) => (
              <option key={mt} value={mt}>
                {MODEL_TYPE_LABELS[mt]}
              </option>
            ))}
          </select>
        </label>
        <label className="model-lab-select">
          指標
          <select value={metric} onChange={(e) => setMetric(e.target.value as Metric)}>
            {METRICS.map((m) => (
              <option key={m.value} value={m.value}>
                {m.label}
              </option>
            ))}
          </select>
        </label>
      </div>

      {error && <p className="signal-queue-error">{error}</p>}

      {!error && values.length === 0 ? (
        <p className="signal-queue-empty">
          このモデルタイプにはまだ champion がありません（学習・品質ゲート通過後に表示されます）
        </p>
      ) : (
        !error && (
          <div
            className="model-lab-chart"
            role="img"
            aria-label={`${MODEL_TYPE_LABELS[modelType]} の${metric === 'skill' ? 'skillスコア' : 'RMSE'}分布`}
          >
            <ResponsiveContainer width="100%" height={260}>
              <BarChart data={bins}>
                <CartesianGrid strokeDasharray="3 3" stroke="var(--color-border)" />
                <XAxis dataKey="range" tick={{ fontSize: 10, fill: 'var(--color-text-muted)' }} />
                <YAxis
                  allowDecimals={false}
                  tick={{ fontSize: 11, fill: 'var(--color-text-muted)' }}
                  label={{ value: '銘柄数', angle: -90, position: 'insideLeft', fontSize: 11 }}
                />
                <Tooltip
                  contentStyle={{ background: 'var(--color-bg-tertiary)', border: '1px solid var(--color-border)' }}
                />
                <Bar dataKey="count" name="銘柄数" fill="var(--color-accent-bright)" />
              </BarChart>
            </ResponsiveContainer>
          </div>
        )
      )}
    </div>
  );
}
