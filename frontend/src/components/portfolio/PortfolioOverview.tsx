'use client';

import { useEffect, useState, type ReactNode } from 'react';
import { fetchPortfolio, type PortfolioSummary } from '@/lib/api/portfolio';
import { HoldingsTable } from './HoldingsTable';
import './portfolio.css';

function formatYen(value: number): string {
  return `¥${Math.round(value).toLocaleString('ja-JP')}`;
}

function directionColor(value: number): string {
  if (value === 0) return 'var(--color-flat)';
  return value > 0 ? 'var(--color-gain)' : 'var(--color-loss)';
}

export function PortfolioOverview(): ReactNode {
  const [summary, setSummary] = useState<PortfolioSummary | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetchPortfolio()
      .then(setSummary)
      .catch(() => setError('ポートフォリオの取得に失敗しました'));
  }, []);

  if (error) return <p className="signal-queue-error">{error}</p>;
  if (summary === null) return null;

  return (
    <div>
      <dl className="signal-card-bracket" style={{ marginBottom: 'var(--spacing-lg)' }}>
        <div>
          <dt>評価額合計</dt>
          <dd>{formatYen(summary.total_value)}</dd>
        </div>
        <div>
          <dt>評価損益</dt>
          <dd style={{ color: directionColor(summary.total_gain_loss) }}>{formatYen(summary.total_gain_loss)}</dd>
        </div>
        <div>
          <dt>騰落率</dt>
          <dd style={{ color: directionColor(summary.total_return_pct) }}>
            {(summary.total_return_pct * 100).toFixed(2)}%
          </dd>
        </div>
      </dl>
      <HoldingsTable holdings={summary.holdings} />
    </div>
  );
}
