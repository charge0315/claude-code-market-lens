'use client';

import { useEffect, useState, type ReactNode } from 'react';
import { CartesianGrid, Legend, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';
import { fetchTrainingTrend, type TrainingModelType, type TrainingTrendPoint } from '@/lib/api/registry';
import './model-lab.css';

// 学習の推移（🆕 P15）: 日別・モデルタイプ別の学習試行件数（成功）を時系列で表示する。
// champion 化の推移は `model_champions` が現行champion 1行のみの upsert 方式のため
// 再構築できず、ここでは学習試行件数のみを扱う（学習カバレッジ側で現在の champion 数を表現）。

const MODEL_TYPES: ReadonlyArray<TrainingModelType> = ['xgboost', 'random_forest', 'lstm', 'transformer'];
const MODEL_TYPE_LABELS: Record<TrainingModelType, string> = {
  xgboost: 'XGBoost',
  random_forest: 'RandomForest',
  lstm: 'LSTM',
  transformer: 'Transformer',
};
const MODEL_TYPE_COLORS: Record<TrainingModelType, string> = {
  xgboost: 'var(--color-accent-bright)',
  random_forest: 'var(--color-term-yellow)',
  lstm: 'var(--color-term-cyan)',
  transformer: 'var(--color-term-purple)',
};

const DAYS_OPTIONS: ReadonlyArray<{ value: number; label: string }> = [
  { value: 7, label: '直近7日' },
  { value: 30, label: '直近30日' },
  { value: 90, label: '直近90日' },
];

type TrendRow = { date: string } & Record<TrainingModelType, number>;

function pivotByDate(points: TrainingTrendPoint[]): TrendRow[] {
  const byDate = new Map<string, TrendRow>();
  for (const p of points) {
    const row = byDate.get(p.date) ?? { date: p.date, xgboost: 0, random_forest: 0, lstm: 0, transformer: 0 };
    row[p.model_type] = p.trained_count;
    byDate.set(p.date, row);
  }
  return Array.from(byDate.values()).sort((a, b) => a.date.localeCompare(b.date));
}

export function TrainingTrendChart(): ReactNode {
  const [days, setDays] = useState(30);
  const [points, setPoints] = useState<TrainingTrendPoint[]>([]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetchTrainingTrend(days)
      .then(setPoints)
      .catch(() => setError('学習推移の取得に失敗しました'));
  }, [days]);

  const rows = pivotByDate(points);

  return (
    <div className="model-lab-panel">
      <div className="model-lab-toolbar">
        <label className="model-lab-select">
          期間
          <select value={days} onChange={(e) => setDays(Number(e.target.value))}>
            {DAYS_OPTIONS.map((d) => (
              <option key={d.value} value={d.value}>
                {d.label}
              </option>
            ))}
          </select>
        </label>
      </div>

      {error && <p className="signal-queue-error">{error}</p>}

      {!error && rows.length === 0 ? (
        <p className="signal-queue-empty">データがありません（銘柄別モデルの学習実行後に表示されます）</p>
      ) : (
        !error && (
          <div className="model-lab-chart" role="img" aria-label="日別・モデルタイプ別の学習件数の推移">
            <ResponsiveContainer width="100%" height={260}>
              <LineChart data={rows}>
                <CartesianGrid strokeDasharray="3 3" stroke="var(--color-border)" />
                <XAxis dataKey="date" tick={{ fontSize: 11, fill: 'var(--color-text-muted)' }} />
                <YAxis allowDecimals={false} tick={{ fontSize: 11, fill: 'var(--color-text-muted)' }} />
                <Tooltip
                  contentStyle={{ background: 'var(--color-bg-tertiary)', border: '1px solid var(--color-border)' }}
                />
                <Legend wrapperStyle={{ fontSize: 11 }} />
                {MODEL_TYPES.map((mt) => (
                  <Line
                    key={mt}
                    type="monotone"
                    dataKey={mt}
                    name={MODEL_TYPE_LABELS[mt]}
                    stroke={MODEL_TYPE_COLORS[mt]}
                    strokeWidth={2}
                    dot={false}
                  />
                ))}
              </LineChart>
            </ResponsiveContainer>
          </div>
        )
      )}
    </div>
  );
}
