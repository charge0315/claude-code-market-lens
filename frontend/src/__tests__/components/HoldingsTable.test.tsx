import { render, screen } from '@testing-library/react';
import { axe } from 'jest-axe';
import { HoldingsTable } from '@/components/portfolio/HoldingsTable';
import type { PortfolioHolding } from '@/lib/api/portfolio';

const HOLDING: PortfolioHolding = {
  holding_id: 'h1',
  symbol: '7203',
  company_name: 'トヨタ',
  sector: '輸送用機器',
  quantity: 100,
  avg_cost: 2500,
  current_price: 3031,
  current_value: 303100,
  cost_basis: 250000,
  gain_loss: 53100,
  return_pct: 0.2124,
  acquired_at: '2026-01-15',
};

describe('HoldingsTable', () => {
  it('保有が無ければ空メッセージを出す', () => {
    render(<HoldingsTable holdings={[]} />);
    expect(screen.getByText('保有銘柄がありません')).toBeInTheDocument();
  });

  it('保有銘柄を評価額・損益付きで表示する', () => {
    render(<HoldingsTable holdings={[HOLDING]} />);

    expect(screen.getByText('7203 トヨタ')).toBeInTheDocument();
    expect(screen.getByText('¥303,100')).toBeInTheDocument();
    expect(screen.getByText('¥53,100')).toBeInTheDocument();
    expect(screen.getByText('21.24%')).toBeInTheDocument();
  });

  it('マイナスの評価損益は損失色で表示する', () => {
    render(<HoldingsTable holdings={[{ ...HOLDING, gain_loss: -1000, return_pct: -0.05 }]} />);

    const cell = screen.getByText('¥-1,000');
    expect(cell).toHaveStyle({ color: 'var(--color-loss)' });
  });

  it('アクセシビリティ違反がない', async () => {
    const { container } = render(<HoldingsTable holdings={[HOLDING]} />);
    expect(await axe(container)).toHaveNoViolations();
  });
});
