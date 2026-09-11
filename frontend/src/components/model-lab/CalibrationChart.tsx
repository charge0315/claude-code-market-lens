'use client';

import { useEffect, useState, type ReactNode } from 'react';
import { CartesianGrid, ComposedChart, Line, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';
import { fetchCalibration, type CalibrationCurve, type EvalScope } from '@/lib/api/eval';
import './model-lab.css';

// 較正曲線（予測確度 → 実測勝率）。対角線（完全較正）との乖離を確認する。

const SCOPES: ReadonlyArray<EvalScope> = ['combined', 'mid_term', 'short_term'];
const SCOPE_LABELS: Record<EvalScope, string> = { combined: '合算', mid_term: '中長期', short_term: '短期' };
const REFERENCE_LINE = [
  { x: 0, y: 0 },
  { x: 1, y: 1 },
];

export function CalibrationChart(): ReactNode {
  const [scope, setScope] = useState<EvalScope>('combined');
  const [curve, setCurve] = useState<CalibrationCurve | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetchCalibration(scope)
      .then(setCurve)
      .catch(() => setError('較正曲線の取得に失敗しました'));
  }, [scope]);

  const actual = (curve?.points ?? []).map((p) => ({ x: p.p_pred, y: p.p_obs, n: p.n }));

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
        {curve?.brier !== null && curve?.brier !== undefined && (
          <span className="model-lab-brier">Brier: {curve.brier.toFixed(4)}</span>
        )}
      </div>

      {error && <p className="signal-queue-error">{error}</p>}

      {actual.length === 0 ? (
        <p className="signal-queue-empty">データがありません（評価バッチ実行後に表示されます）</p>
      ) : (
        <div className="model-lab-chart" role="img" aria-label={`${SCOPE_LABELS[scope]} の較正曲線`}>
          <ResponsiveContainer width="100%" height={260}>
            <ComposedChart>
              <CartesianGrid strokeDasharray="3 3" stroke="var(--color-border)" />
              <XAxis
                dataKey="x"
                type="number"
                domain={[0, 1]}
                tick={{ fontSize: 11, fill: 'var(--color-text-muted)' }}
                label={{ value: '予測確度', position: 'insideBottom', offset: -4, fontSize: 11 }}
              />
              <YAxis
                dataKey="y"
                type="number"
                domain={[0, 1]}
                tick={{ fontSize: 11, fill: 'var(--color-text-muted)' }}
                label={{ value: '実測勝率', angle: -90, position: 'insideLeft', fontSize: 11 }}
              />
              <Tooltip
                contentStyle={{ background: 'var(--color-bg-tertiary)', border: '1px solid var(--color-border)' }}
              />
              <Line
                data={REFERENCE_LINE}
                dataKey="y"
                stroke="var(--color-text-muted)"
                strokeDasharray="4 4"
                dot={false}
                name="完全較正"
              />
              <Line
                data={actual}
                dataKey="y"
                stroke="var(--color-accent-bright)"
                strokeWidth={2}
                dot={{ r: 4 }}
                name="実測"
              />
            </ComposedChart>
          </ResponsiveContainer>
        </div>
      )}
    </div>
  );
}
