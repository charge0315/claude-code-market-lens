'use client';

import { useEffect, useState, type ReactNode } from 'react';
import { Bar, BarChart, CartesianGrid, Legend, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';
import type { TooltipContentProps } from 'recharts';
import { fetchModelCoverage, type ModelCoverage } from '@/lib/api/registry';
import './model-lab.css';

// 学習カバレッジ（🆕 P15）: モデルタイプごとに東証全銘柄の何%を学習済み・champion採用済みかを表示する。

interface ChartRow {
  label: string;
  trainedPct: number;
  championPct: number;
  trainedCount: number;
  championCount: number;
  universeSize: number;
}

function toChartRows(coverage: ModelCoverage[]): ChartRow[] {
  return coverage.map((c) => ({
    label: c.label,
    trainedPct: c.universe_size > 0 ? (c.trained_count / c.universe_size) * 100 : 0,
    championPct: c.universe_size > 0 ? (c.champion_count / c.universe_size) * 100 : 0,
    trainedCount: c.trained_count,
    championCount: c.champion_count,
    universeSize: c.universe_size,
  }));
}

function CoverageTooltip({ active, payload }: TooltipContentProps): ReactNode {
  if (!active || !payload || payload.length === 0) return null;
  const row = payload[0].payload as ChartRow;
  return (
    <div
      style={{
        background: 'var(--color-bg-tertiary)',
        border: '1px solid var(--color-border)',
        padding: 'var(--spacing-sm)',
        fontSize: 'var(--font-size-xs)',
      }}
    >
      <p style={{ margin: 0, fontWeight: 600 }}>{row.label}</p>
      <p style={{ margin: 0 }}>
        学習済み: {row.trainedCount} / {row.universeSize}銘柄（{row.trainedPct.toFixed(1)}%）
      </p>
      <p style={{ margin: 0 }}>
        champion採用: {row.championCount}銘柄（{row.championPct.toFixed(1)}%）
      </p>
    </div>
  );
}

export function ModelCoverageChart(): ReactNode {
  const [coverage, setCoverage] = useState<ModelCoverage[]>([]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetchModelCoverage()
      .then(setCoverage)
      .catch(() => setError('学習カバレッジの取得に失敗しました'));
  }, []);

  const rows = toChartRows(coverage);
  const hasAnyTraining = rows.some((r) => r.trainedCount > 0);

  return (
    <div className="model-lab-panel">
      {error && <p className="signal-queue-error">{error}</p>}

      {!error && !hasAnyTraining ? (
        <p className="signal-queue-empty">データがありません（銘柄別モデルの学習実行後に表示されます）</p>
      ) : (
        !error && (
          <div className="model-lab-chart" role="img" aria-label="モデルタイプ別の学習カバレッジ">
            <ResponsiveContainer width="100%" height={260}>
              <BarChart data={rows}>
                <CartesianGrid strokeDasharray="3 3" stroke="var(--color-border)" />
                <XAxis dataKey="label" tick={{ fontSize: 11, fill: 'var(--color-text-muted)' }} />
                <YAxis
                  domain={[0, 100]}
                  tickFormatter={(v: number) => `${v}%`}
                  tick={{ fontSize: 11, fill: 'var(--color-text-muted)' }}
                />
                <Tooltip content={CoverageTooltip} />
                <Legend wrapperStyle={{ fontSize: 11 }} />
                <Bar dataKey="trainedPct" name="学習済み%" fill="var(--color-accent-bright)" />
                <Bar dataKey="championPct" name="champion採用%" fill="var(--color-term-yellow)" />
              </BarChart>
            </ResponsiveContainer>
          </div>
        )
      )}
    </div>
  );
}
