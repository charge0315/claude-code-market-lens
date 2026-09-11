import { render, screen } from '@testing-library/react';
import { axe } from 'jest-axe';
import { SubScorePanel } from '@/components/stock-detail/SubScorePanel';
import type { PickDetail } from '@/lib/api/picks';

const PICK: PickDetail = {
  pick_id: 'pick-1',
  symbol: '7203',
  direction: 'bullish',
  sub_score_technical: 72,
  sub_score_trend: 65,
  sub_score_fundamental: 50,
  sub_score_sentiment: 40,
  composite_score: 60,
  concordance: 0.8,
  confidence: 75,
  confidence_bucket: 'high',
  rationale_text: 'テクニカルとトレンドが良好',
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
