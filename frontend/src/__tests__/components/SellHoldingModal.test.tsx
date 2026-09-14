import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { axe } from 'jest-axe';
import { SellHoldingModal } from '@/components/portfolio/SellHoldingModal';
import { sellHolding } from '@/lib/api/portfolio';
import type { PortfolioHolding } from '@/lib/api/portfolio';
import { fetchQuote } from '@/lib/api/stock';

jest.mock('@/lib/api/portfolio');
jest.mock('@/lib/api/stock');

const mockSellHolding = sellHolding as jest.MockedFunction<typeof sellHolding>;
const mockFetchQuote = fetchQuote as jest.MockedFunction<typeof fetchQuote>;

const HOLDING: PortfolioHolding = {
  holding_id: 'h1',
  symbol: '7203',
  company_name: 'トヨタ自動車',
  sector: '輸送用機器',
  quantity: 100,
  avg_cost: 2500,
  current_price: 3000,
  current_value: 300000,
  cost_basis: 250000,
  gain_loss: 50000,
  return_pct: 0.2,
  acquired_at: '2026-01-15',
};

describe('SellHoldingModal', () => {
  beforeEach(() => {
    // 既定では最新値が取れない状況を再現し、holding.current_price へのフォールバックを固定する。
    mockFetchQuote.mockRejectedValue(new Error('network error'));
  });

  afterEach(() => {
    jest.clearAllMocks();
  });

  it('保有株数・取得単価を案内し、現在値を売却価格の初期値にする', () => {
    render(<SellHoldingModal holding={HOLDING} onClose={jest.fn()} onSold={jest.fn()} />);

    expect(screen.getByText(/保有株数 100 株/)).toBeInTheDocument();
    expect(screen.getByLabelText('売却価格（円）')).toHaveValue(3000);
    expect(screen.getByLabelText('売却株数')).toHaveValue(100);
  });

  it('開いた時点の最新値が取得できた場合はそれを売却価格の初期値として上書きする', async () => {
    mockFetchQuote.mockResolvedValue({ symbol: '7203', price: 3250, prev_close: 3200, change_pct: 1.56 });

    render(<SellHoldingModal holding={HOLDING} onClose={jest.fn()} onSold={jest.fn()} />);

    await waitFor(() => expect(screen.getByLabelText('売却価格（円）')).toHaveValue(3250));
    expect(screen.getByText(/現在値を初期値にしています/)).toBeInTheDocument();
  });

  it('全量売却するとsellHoldingを呼びonSold・onCloseが呼ばれる', async () => {
    mockSellHolding.mockResolvedValue({
      sell_id: 's1',
      holding_id: 'h1',
      symbol: '7203',
      company_name: 'トヨタ自動車',
      quantity: 100,
      avg_cost: 2500,
      sell_price: 3000,
      realized_pnl: 50000,
      sold_at: '2026-09-13',
      note: null,
    });
    const onSold = jest.fn();
    const onClose = jest.fn();
    const user = userEvent.setup();

    render(<SellHoldingModal holding={HOLDING} onClose={onClose} onSold={onSold} />);
    await user.click(screen.getByRole('button', { name: '売却する' }));

    expect(mockSellHolding).toHaveBeenCalledWith(
      'h1',
      expect.objectContaining({ quantity: 100, sell_price: 3000 }),
    );
    expect(onSold).toHaveBeenCalled();
    expect(onClose).toHaveBeenCalled();
  });

  it('保有株数を超える売却株数はHTML5バリデーションで送信をブロックしsellHoldingを呼ばない', async () => {
    const user = userEvent.setup();
    render(<SellHoldingModal holding={HOLDING} onClose={jest.fn()} onSold={jest.fn()} />);

    const quantityInput = screen.getByLabelText('売却株数') as HTMLInputElement;
    await user.clear(quantityInput);
    await user.type(quantityInput, '150');
    await user.click(screen.getByRole('button', { name: '売却する' }));

    // max=保有株数 の HTML5 制約により、ブラウザが submit イベント自体を発火させない
    // （本コンポーネントの JS バリデーションはこれをすり抜けた場合の保険）。
    expect(quantityInput.validity.valid).toBe(false);
    expect(mockSellHolding).not.toHaveBeenCalled();
  });

  it('売却失敗時はエラーメッセージを表示する', async () => {
    mockSellHolding.mockRejectedValue(new Error('boom'));
    const user = userEvent.setup();

    render(<SellHoldingModal holding={HOLDING} onClose={jest.fn()} onSold={jest.fn()} />);
    await user.click(screen.getByRole('button', { name: '売却する' }));

    expect(await screen.findByText('売却の記録に失敗しました')).toBeInTheDocument();
  });

  it('アクセシビリティ違反がない', async () => {
    const { container } = render(<SellHoldingModal holding={HOLDING} onClose={jest.fn()} onSold={jest.fn()} />);
    expect(await axe(container)).toHaveNoViolations();
  });
});
