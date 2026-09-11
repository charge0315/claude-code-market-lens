'use client';

import { useEffect, useState, type ReactNode } from 'react';
import { fetchWeeklyLearning, type WeeklyLearningSummary } from '@/lib/api/eval';
import './model-lab.css';

// 週次学習差分サマリ（評価指標の変化・昇格判定・ドリフト検知のロールアップ）。

function directionColor(delta: number): string {
  if (delta === 0) return 'var(--color-flat)';
  return delta > 0 ? 'var(--color-gain)' : 'var(--color-loss)';
}

export function WeeklyLearningPanel(): ReactNode {
  const [summary, setSummary] = useState<WeeklyLearningSummary | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetchWeeklyLearning(7)
      .then(setSummary)
      .catch(() => setError('週次学習差分の取得に失敗しました'));
  }, []);

  if (error) return <p className="signal-queue-error">{error}</p>;
  if (summary === null) return null;

  return (
    <div className="model-lab-panel">
      <p className="model-lab-as-of">直近 {summary.window_days} 日（{summary.as_of.slice(0, 10)} 時点）</p>

      {summary.metric_deltas.length === 0 ? (
        <p className="signal-queue-empty">指標の変化はまだありません</p>
      ) : (
        <ul className="weekly-learning-list">
          {summary.metric_deltas.map((d) => (
            <li key={`${d.scope}-${d.metric}`}>
              <span className="weekly-learning-label">
                {d.scope} / {d.metric}
              </span>
              <span>
                {d.before.toFixed(3)} → {d.after.toFixed(3)}
              </span>
              <span style={{ color: directionColor(d.delta) }}>{d.delta >= 0 ? '+' : ''}{d.delta.toFixed(3)}</span>
            </li>
          ))}
        </ul>
      )}

      <p className="model-lab-subheading">直近の昇格判定: {summary.recent_promotions.length} 件</p>
      <p className="model-lab-subheading">直近のドリフト検知: {summary.recent_drift_flags.length} 件</p>
    </div>
  );
}
