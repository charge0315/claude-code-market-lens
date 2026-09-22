import { render, screen, waitFor } from '@testing-library/react';
import { axe } from 'jest-axe';
import { ChartPanel } from '@/components/chart/ChartPanel';
import { fetchOhlc, fetchQuote } from '@/lib/api/stock';
import type { Quote } from '@/lib/api/stock';

jest.mock('@/lib/api/stock');

const mockFetchQuote = fetchQuote as jest.MockedFunction<typeof fetchQuote>;
const mockFetchOhlc = fetchOhlc as jest.MockedFunction<typeof fetchOhlc>;

function quote(overrides?: Partial<Quote>): Quote {
  return { symbol: '7203', price: 2500, prev_close: 2400, change_pct: 4.17, ...overrides };
}

describe('ChartPanel', () => {
  beforeEach(() => {
    mockFetchOhlc.mockResolvedValue({ bars: [], events: [] });
  });

  afterEach(() => {
    jest.clearAllMocks();
  });

  it('symbolが無ければ案内文のみ表示する', () => {
    render(<ChartPanel symbol={null} />);

    expect(screen.getByText('銘柄を検索するか、一覧から選択してください')).toBeInTheDocument();
  });

  it('現在値と騰落率を表示する', async () => {
    mockFetchQuote.mockResolvedValue(quote());

    render(<ChartPanel symbol="7203" />);

    expect(await screen.findByText('¥2,500')).toBeInTheDocument();
    expect(screen.getByText('+4.17%')).toBeInTheDocument();
  });

  it('下落時は符号なしのマイナス表記で騰落率を表示する', async () => {
    mockFetchQuote.mockResolvedValue(quote({ change_pct: -1.5 }));

    render(<ChartPanel symbol="7203" />);

    expect(await screen.findByText('-1.50%')).toBeInTheDocument();
  });

  it('現在値取得に失敗してもチャートは表示を試みる', async () => {
    mockFetchQuote.mockRejectedValue(new Error('boom'));

    render(<ChartPanel symbol="7203" />);

    expect(await screen.findByText('現在値の取得に失敗しました')).toBeInTheDocument();
    await waitFor(() => expect(mockFetchOhlc).toHaveBeenCalledWith('7203', '6mo', '1d'));
  });

  it('symbolが切り替わると現在値を再取得する', async () => {
    mockFetchQuote.mockResolvedValue(quote());
    const { rerender } = render(<ChartPanel symbol="7203" />);
    await waitFor(() => expect(mockFetchQuote).toHaveBeenCalledWith('7203'));

    mockFetchQuote.mockResolvedValue(quote({ symbol: '9984', price: 9000, change_pct: 0 }));
    rerender(<ChartPanel symbol="9984" />);

    await waitFor(() => expect(mockFetchQuote).toHaveBeenCalledWith('9984'));
    expect(await screen.findByText('¥9,000')).toBeInTheDocument();
  });

  it('足種セレクタ（日足/60分足/15分足）を表示する（🆕、chart画面限定の粒度切り替え）', async () => {
    mockFetchQuote.mockResolvedValue(quote());

    render(<ChartPanel symbol="7203" />);

    expect(await screen.findByRole('group', { name: '足種' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: '日足' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: '60分足' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: '15分足' })).toBeInTheDocument();
  });

  it('アクセシビリティ違反がない', async () => {
    mockFetchQuote.mockResolvedValue(quote());

    const { container } = render(<ChartPanel symbol="7203" />);
    await waitFor(() => expect(mockFetchQuote).toHaveBeenCalled());

    expect(await axe(container)).toHaveNoViolations();
  });
});
