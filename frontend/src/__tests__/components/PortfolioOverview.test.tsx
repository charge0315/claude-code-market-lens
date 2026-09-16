import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { axe } from 'jest-axe';
import { PortfolioOverview } from '@/components/portfolio/PortfolioOverview';
import { fetchPortfolio, fetchSellHistory } from '@/lib/api/portfolio';
import type { PortfolioSummary } from '@/lib/api/portfolio';
import { fetchPicks, fetchShadowPicks } from '@/lib/api/picks';
import type { PickSummary } from '@/lib/api/picks';
import { fetchQuote } from '@/lib/api/stock';

jest.mock('@/lib/api/portfolio');
jest.mock('@/lib/api/stock');
jest.mock('@/lib/api/picks');

const mockFetchPortfolio = fetchPortfolio as jest.MockedFunction<typeof fetchPortfolio>;
const mockFetchSellHistory = fetchSellHistory as jest.MockedFunction<typeof fetchSellHistory>;
const mockFetchPicks = fetchPicks as jest.MockedFunction<typeof fetchPicks>;
const mockFetchShadowPicks = fetchShadowPicks as jest.MockedFunction<typeof fetchShadowPicks>;
const mockFetchQuote = fetchQuote as jest.MockedFunction<typeof fetchQuote>;

beforeEach(() => {
  mockFetchSellHistory.mockResolvedValue([]);
  mockFetchPicks.mockResolvedValue([]);
  mockFetchShadowPicks.mockResolvedValue([]);
  // AddHoldingModal/SellHoldingModal が開いた時点の最新値取得に使う。自動モックのままだと
  // 戻り値が undefined になり `.then` 呼び出しで例外になるため、既定の reject を与えておく
  // （個々のテストは suggestedPrice / holding.current_price へのフォールバックだけを見る）。
  mockFetchQuote.mockRejectedValue(new Error('network error'));
});

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

describe('PortfolioOverview', () => {
  afterEach(() => {
    jest.clearAllMocks();
  });

  it('評価額・評価損益・保有一覧を表示する', async () => {
    mockFetchPortfolio.mockResolvedValue(SUMMARY);

    render(<PortfolioOverview />);

    expect(await screen.findByText('7203 トヨタ')).toBeInTheDocument();
    expect(screen.getAllByText('¥303,100')).toHaveLength(2); // 評価額合計 + 保有明細の評価額
    expect(screen.getAllByText('21.24%')).toHaveLength(2); // 騰落率サマリ + 保有明細
  });

  it('取得失敗でエラーメッセージを出す', async () => {
    mockFetchPortfolio.mockRejectedValue(new Error('boom'));

    render(<PortfolioOverview />);

    expect(await screen.findByText('ポートフォリオの取得に失敗しました')).toBeInTheDocument();
  });

  it('AIピックから選択すると推奨買値を取得単価の初期値にしたポップアップを開く', async () => {
    mockFetchPortfolio.mockResolvedValue(SUMMARY);
    const aiPick: PickSummary = {
      pick_id: 'p1',
      issued_at: '2026-09-13T08:50:00+09:00',
      horizon_type: 'mid_term',
      symbol: '9256',
      company_name: 'サクシード',
      direction: 'bullish',
      entry: 975,
      stop: 800,
      target: 1250,
      composite_score: 80,
      concordance: 1,
      confidence: 72,
      confidence_bucket: 'high',
      rationale_text: 'x',
      model_version: 'v1',
      source_contributions: {},
      current_price: null,
      change_pct: null,
      spark: [],
      reasoning_tags: [],
    };
    mockFetchPicks.mockImplementation((horizonType) => Promise.resolve(horizonType === 'mid_term' ? [aiPick] : []));
    const user = userEvent.setup();

    render(<PortfolioOverview />);
    await user.click(await screen.findByRole('button', { name: /9256（サクシード）/ }));

    expect(await screen.findByText('ポートフォリオに追加: 9256（サクシード）')).toBeInTheDocument();
    expect(screen.getByLabelText('取得単価（円）')).toHaveValue(975);
  });

  it('アクセシビリティ違反がない', async () => {
    mockFetchPortfolio.mockResolvedValue(SUMMARY);

    const { container } = render(<PortfolioOverview />);
    await waitFor(() => expect(mockFetchPortfolio).toHaveBeenCalled());

    expect(await axe(container)).toHaveNoViolations();
  });
});
