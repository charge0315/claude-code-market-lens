import { render, screen } from '@testing-library/react';
import { axe } from 'jest-axe';
import { SellHistoryTable } from '@/components/portfolio/SellHistoryTable';
import { fetchSellHistory } from '@/lib/api/portfolio';
import type { SellHistoryEntry } from '@/lib/api/portfolio';

jest.mock('@/lib/api/portfolio');

const mockFetchSellHistory = fetchSellHistory as jest.MockedFunction<typeof fetchSellHistory>;

const ENTRY: SellHistoryEntry = {
  sell_id: 's1',
  holding_id: 'h1',
  symbol: '7203',
  company_name: 'トヨタ自動車',
  quantity: 50,
  avg_cost: 2500,
  sell_price: 3000,
  realized_pnl: 25000,
  sold_at: '2026-09-13',
  note: '利確',
};

describe('SellHistoryTable', () => {
  afterEach(() => {
    jest.clearAllMocks();
  });

  it('履歴が無ければ空メッセージを出す', async () => {
    mockFetchSellHistory.mockResolvedValue([]);
    render(<SellHistoryTable reloadKey={0} />);

    expect(await screen.findByText('売却履歴はまだありません')).toBeInTheDocument();
  });

  it('売却履歴を表示する', async () => {
    mockFetchSellHistory.mockResolvedValue([ENTRY]);
    render(<SellHistoryTable reloadKey={0} />);

    expect(await screen.findByText('7203（トヨタ自動車）')).toBeInTheDocument();
    expect(screen.getByText('¥25,000')).toBeInTheDocument();
    expect(screen.getByText('利確')).toBeInTheDocument();
  });

  it('reloadKeyが変わると再取得する', async () => {
    mockFetchSellHistory.mockResolvedValue([]);
    const { rerender } = render(<SellHistoryTable reloadKey={0} />);
    await screen.findByText('売却履歴はまだありません');

    rerender(<SellHistoryTable reloadKey={1} />);

    expect(mockFetchSellHistory).toHaveBeenCalledTimes(2);
  });

  it('取得失敗でエラーメッセージを出す', async () => {
    mockFetchSellHistory.mockRejectedValue(new Error('boom'));
    render(<SellHistoryTable reloadKey={0} />);

    expect(await screen.findByText('売却履歴の取得に失敗しました')).toBeInTheDocument();
  });

  it('アクセシビリティ違反がない', async () => {
    mockFetchSellHistory.mockResolvedValue([ENTRY]);
    const { container } = render(<SellHistoryTable reloadKey={0} />);
    await screen.findByText('7203（トヨタ自動車）');

    expect(await axe(container)).toHaveNoViolations();
  });
});
