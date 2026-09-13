import { render, screen, waitFor } from '@testing-library/react';
import { axe } from 'jest-axe';
import { MarketTickerBar } from '@/components/dashboard/MarketTickerBar';
import { fetchMarketSnapshot } from '@/lib/api/market';
import type { MarketSnapshot } from '@/lib/api/market';

jest.mock('@/lib/api/market');

const mockFetchSnapshot = fetchMarketSnapshot as jest.MockedFunction<typeof fetchMarketSnapshot>;

const SNAPSHOT: MarketSnapshot = {
  indices: [
    { label: '日経平均株価', value: 42_318.75, change: 386.2, change_pct: 0.92, spark: [41_900.0, 42_318.75] },
    { label: 'グロース250', value: 742.18, change: -4.36, change_pct: -0.58, spark: [746.5, 742.18] },
  ],
  market_status: 'ザラ場中',
  updated_at: '2026-09-12T14:32:00+09:00',
};

describe('MarketTickerBar', () => {
  afterEach(() => {
    jest.clearAllMocks();
  });

  it('指数タイルと市況ステータス・更新時刻を表示する', async () => {
    mockFetchSnapshot.mockResolvedValue(SNAPSHOT);

    render(<MarketTickerBar />);

    expect(await screen.findByText('日経平均株価')).toBeInTheDocument();
    expect(screen.getByText('42,318.75')).toBeInTheDocument();
    expect(screen.getByText('+386.20（+0.92%）')).toBeInTheDocument();
    expect(screen.getByText('グロース250')).toBeInTheDocument();
    expect(screen.getByText('-4.36（-0.58%）')).toBeInTheDocument();
    expect(screen.getByText('ザラ場中')).toBeInTheDocument();
    expect(screen.getByText('更新 2026-09-12 14:32')).toBeInTheDocument();
  });

  it('指数が0件なら何も表示しない', () => {
    mockFetchSnapshot.mockResolvedValue({ ...SNAPSHOT, indices: [] });

    const { container } = render(<MarketTickerBar />);

    expect(container).toBeEmptyDOMElement();
  });

  it('取得失敗時は何も表示しない（フェイルソフト）', async () => {
    mockFetchSnapshot.mockRejectedValue(new Error('network error'));

    const { container } = render(<MarketTickerBar />);

    await waitFor(() => expect(mockFetchSnapshot).toHaveBeenCalled());
    expect(container).toBeEmptyDOMElement();
  });

  it('アクセシビリティ違反がない', async () => {
    mockFetchSnapshot.mockResolvedValue(SNAPSHOT);
    const { container } = render(<MarketTickerBar />);
    await screen.findByText('日経平均株価');

    expect(await axe(container)).toHaveNoViolations();
  });
});
