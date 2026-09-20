import type { ReactNode } from 'react';
import type { PickDetail, SubScores } from '@/lib/api/picks';
import './stock-detail.css';

// 4 分析（テクニカル/トレンド/ファンダメンタル/センチメント）内訳バー。

const LABELS: Record<keyof SubScores, string> = {
  technical: 'テクニカル',
  trend: 'トレンド',
  fundamental: 'ファンダメンタル',
  sentiment: 'センチメント',
};

export function SubScorePanel({ pick }: { pick: PickDetail }): ReactNode {
  const rows = (Object.keys(LABELS) as Array<keyof SubScores>).map((key) => ({
    key,
    label: LABELS[key],
    value: pick.sub_scores[key],
  }));

  return (
    <div className="sub-score-panel">
      <ul className="sub-score-list" aria-label={`${pick.symbol} の4分析内訳`}>
        {rows.map((row) => (
          <li key={row.key} className="sub-score-card">
            <div className="sub-score-card-header">
              <span className="sub-score-label">{row.label}</span>
              <span className="sub-score-value num">{row.value.toFixed(0)}</span>
            </div>
            <span className="sub-score-track">
              <span className="sub-score-fill" style={{ width: `${Math.max(0, Math.min(100, row.value))}%` }} />
            </span>
          </li>
        ))}
      </ul>
      <p className="sub-score-rationale">{pick.rationale_text}</p>
    </div>
  );
}
