import { render, screen } from '@testing-library/react';
import { axe } from 'jest-axe';
import { SubScorePanel } from '@/components/stock-detail/SubScorePanel';
import type { PickDetail } from '@/lib/api/picks';

const PICK: PickDetail = {
  pick_id: 'pick-1',
  run_id: 'run-1',
  issued_at: '2026-09-12T08:50:00+09:00',
  horizon_type: 'mid_term',
  symbol: '7203',
  company_name: 'トヨタ自動車',
  direction: 'bullish',
  entry: 1000,
  stop: 950,
  target: 1100,
  sub_scores: { technical: 72, trend: 65, fundamental: 50, sentiment: 40 },
  composite_score: 60,
  concordance: 0.8,
  confidence_raw: 75,
  confidence: 75,
  confidence_bucket: 'high',
  rationale_struct: {},
  rationale_text: 'テクニカルとトレンドが良好',
  model_version: 'test-model',
  source_contributions: {},
  created_at: '2026-09-12T08:50:01+09:00',
};

describe('SubScorePanel', () => {
  it('4分析のラベルと値を表示する', () => {
    render(<SubScorePanel pick={PICK} />);

    expect(screen.getByText('テクニカル')).toBeInTheDocument();
    expect(screen.getByText('72')).toBeInTheDocument();
    expect(screen.getByText('トレンド')).toBeInTheDocument();
    expect(screen.getByText('ファンダメンタル')).toBeInTheDocument();
    expect(screen.getByText('センチメント')).toBeInTheDocument();
    expect(screen.getByText('テクニカルとトレンドが良好')).toBeInTheDocument();
  });

  it('アクセシビリティ違反がない', async () => {
    const { container } = render(<SubScorePanel pick={PICK} />);
    expect(await axe(container)).toHaveNoViolations();
  });
});
