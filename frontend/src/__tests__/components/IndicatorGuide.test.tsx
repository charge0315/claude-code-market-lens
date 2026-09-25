import { render, screen } from '@testing-library/react';
import { axe } from 'jest-axe';
import { IndicatorGuide } from '@/components/chart/IndicatorGuide';

describe('IndicatorGuide', () => {
  it('チャートの凡例と同じ名称で各指標の説明を表示する', () => {
    render(<IndicatorGuide />);

    expect(screen.getByText('SMA_5 / SMA_25 / SMA_75')).toBeInTheDocument();
    expect(screen.getByText('MACD')).toBeInTheDocument();
    expect(screen.getByText('RSI')).toBeInTheDocument();
    expect(screen.getByText('ストキャスティクス（%K / %D）')).toBeInTheDocument();
  });

  it('アクセシビリティ違反がない', async () => {
    const { container } = render(<IndicatorGuide />);

    expect(await axe(container)).toHaveNoViolations();
  });
});
