'use client';

import { useEffect, useState, type ReactNode } from 'react';
import { CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';
import { fetchGrowth, type EvalScope, type EvalSnapshot } from '@/lib/api/eval';
import './model-lab.css';

// 評価指標の成長曲線（AUC / IC / 較正誤差(Brier) / 勝率 / Sharpe）。scope × metric で絞り込む。

const SCOPES: ReadonlyArray<EvalScope> = ['combined', 'mid_term', 'short_term'];
const SCOPE_LABELS: Record<EvalScope, string> = { combined: '合算', mid_term: '中長期', short_term: '短期' };

const METRICS: ReadonlyArray<{ value: string; label: string }> = [
  { value: 'win_rate', label: '勝率' },
  { value: 'ic', label: 'IC' },
  { value: 'brier', label: '較正誤差 (Brier)' },
  { value: 'auc', label: 'AUC' },
  { value: 'sharpe', label: 'Sharpe' },
];

function formatDate(iso: string): string {
  return iso.slice(0, 10);
}

export function GrowthChart(): ReactNode {
  const [scope, setScope] = useState<EvalScope>('combined');
  const [metric, setMetric] = useState('win_rate');
  const [snapshots, setSnapshots] = useState<EvalSnapshot[]>([]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetchGrowth({ scope, metric, limit: 500 })
      .then(setSnapshots)
      .catch(() => setError('成長曲線の取得に失敗しました'));
  }, [scope, metric]);

  const points = snapshots.map((s) => ({ date: formatDate(s.computed_at), value: s.metric_value }));

  return (
    <div className="model-lab-panel">
      <div className="model-lab-toolbar">
        <label className="model-lab-select">
          scope
          <select value={scope} onChange={(e) => setScope(e.target.value as EvalScope)}>
            {SCOPES.map((s) => (
              <option key={s} value={s}>
                {SCOPE_LABELS[s]}
              </option>
            ))}
          </select>
        </label>
        <label className="model-lab-select">
          指標
          <select value={metric} onChange={(e) => setMetric(e.target.value)}>
            {METRICS.map((m) => (
              <option key={m.value} value={m.value}>
                {m.label}
              </option>
            ))}
          </select>
        </label>
      </div>

      {error && <p className="signal-queue-error">{error}</p>}

      {points.length === 0 ? (
        <p className="signal-queue-empty">データがありません（評価バッチ実行後に表示されます）</p>
      ) : (
        <div className="model-lab-chart" role="img" aria-label={`${SCOPE_LABELS[scope]} / ${metric} の成長曲線`}>
          <ResponsiveContainer width="100%" height={260}>
            <LineChart data={points}>
              <CartesianGrid strokeDasharray="3 3" stroke="var(--color-border)" />
              <XAxis dataKey="date" tick={{ fontSize: 11, fill: 'var(--color-text-muted)' }} />
              <YAxis tick={{ fontSize: 11, fill: 'var(--color-text-muted)' }} />
              <Tooltip
                contentStyle={{ background: 'var(--color-bg-tertiary)', border: '1px solid var(--color-border)' }}
              />
              <Line type="monotone" dataKey="value" stroke="var(--color-accent-bright)" dot={false} strokeWidth={2} />
            </LineChart>
          </ResponsiveContainer>
        </div>
      )}
    </div>
  );
}
