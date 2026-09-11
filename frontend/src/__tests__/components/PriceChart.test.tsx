import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { axe } from 'jest-axe';
import { PriceChart } from '@/components/stock-detail/PriceChart';
import { fetchOhlc } from '@/lib/api/stock';
import type { OhlcBar } from '@/lib/api/stock';

jest.mock('@/lib/api/stock');

const mockFetchOhlc = fetchOhlc as jest.MockedFunction<typeof fetchOhlc>;

const BAR: OhlcBar = { time: '2026-06-01', open: 1000, high: 1020, low: 990, close: 1010, volume: 1_000_000 };

describe('PriceChart', () => {
  afterEach(() => {
    jest.clearAllMocks();
  });

  it('銘柄の OHLC を取得する', async () => {
    mockFetchOhlc.mockResolvedValue([BAR]);

    render(<PriceChart symbol="7203" />);

    await waitFor(() => expect(mockFetchOhlc).toHaveBeenCalledWith('7203', '6mo'));
  });

  it('データが無ければ案内文を出す', async () => {
    mockFetchOhlc.mockResolvedValue([]);

    render(<PriceChart symbol="7203" />);

    expect(await screen.findByText('株価データがありません')).toBeInTheDocument();
  });

  it('期間ボタンを切り替えると再取得する', async () => {
    mockFetchOhlc.mockResolvedValue([BAR]);
    const user = userEvent.setup();

    render(<PriceChart symbol="7203" />);
    await waitFor(() => expect(mockFetchOhlc).toHaveBeenCalledWith('7203', '6mo'));

    await user.click(screen.getByRole('button', { name: '1年' }));

    await waitFor(() => expect(mockFetchOhlc).toHaveBeenCalledWith('7203', '1y'));
  });

  it('取得失敗でエラーメッセージを出す', async () => {
    mockFetchOhlc.mockRejectedValue(new Error('boom'));

    render(<PriceChart symbol="7203" />);

    expect(await screen.findByText('株価データの取得に失敗しました')).toBeInTheDocument();
  });

  it('アクセシビリティ違反がない', async () => {
    mockFetchOhlc.mockResolvedValue([BAR]);

    const { container } = render(<PriceChart symbol="7203" />);
    await waitFor(() => expect(mockFetchOhlc).toHaveBeenCalled());

    expect(await axe(container)).toHaveNoViolations();
  });
});
