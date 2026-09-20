import { render, screen, waitFor } from '@testing-library/react';
import { axe } from 'jest-axe';
import { PortfolioSummarySection } from '@/components/dashboard/PortfolioSummarySection';
import { fetchPortfolio } from '@/lib/api/portfolio';
import type { PortfolioSummary } from '@/lib/api/portfolio';

jest.mock('@/lib/api/portfolio');

const mockFetchPortfolio = fetchPortfolio as jest.MockedFunction<typeof fetchPortfolio>;

const SUMMARY: PortfolioSummary = {
  total_value: 303100,
  total_cost: 250000,
  total_gain_loss: 53100,
  total_return_pct: 0.2124,
  day_gain_loss: 3700,
  holdings: [
    {
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
    },
  ],
  sector_allocations: [{ sector: '輸送用機器', value: 303100, pct: 100 }],
  holding_count: 1,
  updated_at: '2026-09-11T20:00:00+09:00',
};

describe('PortfolioSummarySection', () => {
  afterEach(() => {
    jest.clearAllMocks();
  });

  it('トータル収支と保有銘柄の概要を表示する', async () => {
    mockFetchPortfolio.mockResolvedValue(SUMMARY);

    render(<PortfolioSummarySection />);

    expect(await screen.findAllByText('¥303,100')).toHaveLength(2); // 評価額合計 + 保有銘柄行
    expect(screen.getByText('21.24%')).toBeInTheDocument();
    expect(screen.getByText('1銘柄')).toBeInTheDocument();
    expect(screen.getByText('7203 トヨタ')).toBeInTheDocument();
    expect(screen.getByText('ポートフォリオで詳細を見る')).toBeInTheDocument();
  });

  it('保有件数がプレビュー上限を超える場合は残数を表示する', async () => {
    const holdings = Array.from({ length: 8 }, (_, i) => ({
      ...SUMMARY.holdings[0],
      holding_id: `h${i}`,
      symbol: `${1000 + i}`,
    }));
    mockFetchPortfolio.mockResolvedValue({ ...SUMMARY, holdings, holding_count: holdings.length });

    render(<PortfolioSummarySection />);

    expect(await screen.findByText('ほか2銘柄')).toBeInTheDocument();
  });

  it('保有銘柄が無ければ空メッセージを出す', async () => {
    mockFetchPortfolio.mockResolvedValue({ ...SUMMARY, holdings: [], holding_count: 0 });

    render(<PortfolioSummarySection />);

    expect(await screen.findByText('保有銘柄がありません')).toBeInTheDocument();
  });

  it('取得失敗時は何も表示しない（フェイルソフト）', async () => {
    mockFetchPortfolio.mockRejectedValue(new Error('network error'));

    const { container } = render(<PortfolioSummarySection />);

    await waitFor(() => expect(mockFetchPortfolio).toHaveBeenCalled());
    expect(container).toBeEmptyDOMElement();
  });

  it('アクセシビリティ違反がない', async () => {
    mockFetchPortfolio.mockResolvedValue(SUMMARY);
    const { container } = render(<PortfolioSummarySection />);
    await screen.findByText('7203 トヨタ');

    expect(await axe(container)).toHaveNoViolations();
  });
});
