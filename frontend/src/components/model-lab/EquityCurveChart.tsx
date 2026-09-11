'use client';

import { useEffect, useState, type ReactNode } from 'react';
import { CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';
import { fetchEquityCurve, type EquityCurveResult, type EvalScope } from '@/lib/api/eval';
import './model-lab.css';

// ピック累積成績（エクイティカーブ）。決着済みピックの超過リターンを勝敗確定順に累積する。

const SCOPES: ReadonlyArray<EvalScope> = ['combined', 'mid_term', 'short_term'];
const SCOPE_LABELS: Record<EvalScope, string> = { combined: '合算', mid_term: '中長期', short_term: '短期' };
const HORIZONS = [5, 20, 60] as const;

function directionColor(value: number): string {
  if (value === 0) return 'var(--color-flat)';
  return value > 0 ? 'var(--color-gain)' : 'var(--color-loss)';
}

export function EquityCurveChart(): ReactNode {
  const [scope, setScope] = useState<EvalScope>('combined');
  const [horizon, setHorizon] = useState<number>(20);
  const [result, setResult] = useState<EquityCurveResult | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetchEquityCurve(scope, horizon)
      .then(setResult)
      .catch(() => setError('エクイティカーブの取得に失敗しました'));
  }, [scope, horizon]);

  const points = (result?.equity ?? []).map((v, i) => ({ i: i + 1, equity: v }));

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
          ホライズン
          <select value={horizon} onChange={(e) => setHorizon(Number(e.target.value))}>
            {HORIZONS.map((h) => (
              <option key={h} value={h}>
                {h}営業日
              </option>
            ))}
          </select>
        </label>
        {result && result.n > 0 && (
          <span className="model-lab-brier">
            n={result.n} / 最大DD {(result.max_drawdown * 100).toFixed(1)}%
            {result.sharpe !== null && ` / Sharpe ${result.sharpe.toFixed(2)}`}
            {result.win_rate !== null && (
              <>
                {' / 勝率 '}
                <span style={{ color: directionColor(result.win_rate - 0.5) }}>{(result.win_rate * 100).toFixed(1)}%</span>
              </>
            )}
          </span>
        )}
      </div>

      {error && <p className="signal-queue-error">{error}</p>}

      {points.length === 0 ? (
        <p className="signal-queue-empty">決着済みピックがまだありません</p>
      ) : (
        <div className="model-lab-chart" role="img" aria-label={`${SCOPE_LABELS[scope]} のピック累積成績（エクイティカーブ）`}>
          <ResponsiveContainer width="100%" height={260}>
            <LineChart data={points}>
              <CartesianGrid strokeDasharray="3 3" stroke="var(--color-border)" />
              <XAxis dataKey="i" tick={{ fontSize: 11, fill: 'var(--color-text-muted)' }} label={{ value: '決着順', position: 'insideBottom', offset: -4, fontSize: 11 }} />
              <YAxis tick={{ fontSize: 11, fill: 'var(--color-text-muted)' }} />
              <Tooltip
                contentStyle={{ background: 'var(--color-bg-tertiary)', border: '1px solid var(--color-border)' }}
              />
              <Line type="monotone" dataKey="equity" stroke="var(--color-accent-bright)" dot={false} strokeWidth={2} />
            </LineChart>
          </ResponsiveContainer>
        </div>
      )}
    </div>
  );
}
