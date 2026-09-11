import type { ReactNode } from 'react';
import type { PickDetail } from '@/lib/api/picks';
import './stock-detail.css';

// 4 分析（テクニカル/トレンド/ファンダメンタル/センチメント）内訳バー。

const LABELS = {
  sub_score_technical: 'テクニカル',
  sub_score_trend: 'トレンド',
  sub_score_fundamental: 'ファンダメンタル',
  sub_score_sentiment: 'センチメント',
} as const;

export function SubScorePanel({ pick }: { pick: PickDetail }): ReactNode {
  const rows = (Object.keys(LABELS) as Array<keyof typeof LABELS>).map((key) => ({
    key,
    label: LABELS[key],
    value: pick[key],
  }));

  return (
    <div className="sub-score-panel">
      <ul className="sub-score-list" aria-label={`${pick.symbol} の4分析内訳`}>
        {rows.map((row) => (
          <li key={row.key} className="sub-score-row">
            <span className="sub-score-label">{row.label}</span>
            <span className="sub-score-track">
              <span className="sub-score-fill" style={{ width: `${Math.max(0, Math.min(100, row.value))}%` }} />
            </span>
            <span className="sub-score-value num">{row.value.toFixed(0)}</span>
          </li>
        ))}
      </ul>
      <p className="sub-score-rationale">{pick.rationale_text}</p>
    </div>
  );
}
