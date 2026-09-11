import { render, screen } from '@testing-library/react';
import { axe } from 'jest-axe';
import { ShapBar } from '@/components/pipeline/ShapBar';

describe('ShapBar', () => {
  it('データが無ければ案内文を出す', () => {
    render(<ShapBar sourceContributions={{}} />);
    expect(screen.getByText('寄与度データがありません')).toBeInTheDocument();
  });

  it('各ファクターを日本語ラベルと寄与度で表示する', () => {
    render(
      <ShapBar
        sourceContributions={{
          technical: { weight_share: 0.5, contribution: 30.2, score: 60 },
          ml_prediction: { weight_share: 0.3, contribution: -5.1, score: 40 },
        }}
      />,
    );
    expect(screen.getByText('テクニカル')).toBeInTheDocument();
    expect(screen.getByText('AI予測')).toBeInTheDocument();
    expect(screen.getByText('30.2')).toBeInTheDocument();
    expect(screen.getByText('-5.1')).toBeInTheDocument();
  });

  it('未知のファクターキーはそのまま表示する', () => {
    render(<ShapBar sourceContributions={{ unknown_factor: { weight_share: 1, contribution: 10, score: 50 } }} />);
    expect(screen.getByText('unknown_factor')).toBeInTheDocument();
  });

  it('アクセシビリティ違反がない', async () => {
    const { container } = render(
      <ShapBar sourceContributions={{ technical: { weight_share: 1, contribution: 20, score: 55 } }} />,
    );
    expect(await axe(container)).toHaveNoViolations();
  });
});
