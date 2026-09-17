import { render, screen } from '@testing-library/react';
import { axe } from 'jest-axe';
import { PickedTickersList } from '@/components/stock-detail/PickedTickersList';
import { fetchPicks, fetchShadowPicks } from '@/lib/api/picks';
import type { PickSummary, ShadowPickSummary, HorizonType } from '@/lib/api/picks';
import { fetchPortfolio } from '@/lib/api/portfolio';
import type { PortfolioHolding, PortfolioSummary } from '@/lib/api/portfolio';
import { todayJst } from '@/lib/jstDate';

jest.mock('@/lib/api/picks');
jest.mock('@/lib/api/portfolio');

const mockFetchPicks = fetchPicks as jest.MockedFunction<typeof fetchPicks>;
const mockFetchShadowPicks = fetchShadowPicks as jest.MockedFunction<typeof fetchShadowPicks>;
const mockFetchPortfolio = fetchPortfolio as jest.MockedFunction<typeof fetchPortfolio>;

function holding(overrides: Partial<PortfolioHolding>): PortfolioHolding {
  return {
    holding_id: 'h1',
    symbol: '6758',
    company_name: 'ソニーグループ',
    sector: null,
    quantity: 100,
    avg_cost: 1000,
    current_price: null,
    current_value: null,
    cost_basis: 100000,
    gain_loss: null,
    return_pct: null,
    acquired_at: '2026-01-01',
    ...overrides,
  };
}

function portfolioSummary(holdings: PortfolioHolding[]): PortfolioSummary {
  return {
    total_value: 0,
    total_cost: 0,
    total_gain_loss: 0,
    total_return_pct: 0,
    day_gain_loss: null,
    holdings,
    sector_allocations: [],
    holding_count: holdings.length,
    updated_at: '2026-09-15T00:00:00+09:00',
  };
}

function pick(overrides: Partial<PickSummary>): PickSummary {
  return {
    pick_id: 'p1',
    issued_at: '2026-09-12T08:50:00+09:00',
    horizon_type: 'mid_term',
    symbol: '7203',
    company_name: 'トヨタ自動車',
    direction: 'bullish',
    entry: 1000,
    stop: 950,
    target: 1100,
    composite_score: 60,
    concordance: 0.8,
    confidence: 70,
    confidence_bucket: 'high',
    rationale_text: 'x',
    model_version: 'v1',
    source_contributions: {},
    current_price: null,
    change_pct: null,
    spark: [],
    reasoning_tags: [],
    ...overrides,
  };
}

function shadowPick(overrides: Partial<ShadowPickSummary>): ShadowPickSummary {
  return {
    shadow_id: 's1',
    pick_id: null,
    challenger_version: 'gemini:test',
    issued_at: '2026-09-12T08:50:00+09:00',
    horizon_type: 'mid_term',
    symbol: '9984',
    company_name: 'ソフトバンクグループ',
    direction: 'bullish',
    entry: 1000,
    stop: 950,
    target: 1100,
    confidence: 70,
    reasoning: null,
    risk_factors: [],
    holding_period_days: null,
    current_price: null,
    change_pct: null,
    spark: [],
    ...overrides,
  };
}

describe('PickedTickersList', () => {
  beforeEach(() => {
    mockFetchShadowPicks.mockResolvedValue([]);
    mockFetchPortfolio.mockResolvedValue(portfolioSummary([]));
  });

  afterEach(() => {
    jest.clearAllMocks();
  });

  it('ピック・保有銘柄が無ければ案内文を出す', async () => {
    mockFetchPicks.mockResolvedValue([]);

    render(<PickedTickersList selectedSymbol={null} />);

    expect(await screen.findByText('本日のピック・保有銘柄はまだありません')).toBeInTheDocument();
  });

  it('当日日付をピックAPIへ渡す（過去分は含めない）', async () => {
    mockFetchPicks.mockResolvedValue([]);

    render(<PickedTickersList selectedSymbol={null} />);

    await screen.findByText('本日のピック・保有銘柄はまだありません');
    const today = todayJst();
    expect(mockFetchPicks).toHaveBeenCalledWith('mid_term', { date: today, limit: 50 });
    expect(mockFetchPicks).toHaveBeenCalledWith('short_term', { date: today, limit: 50 });
    expect(mockFetchShadowPicks).toHaveBeenCalledWith('mid_term', { date: today, limit: 50 });
    expect(mockFetchShadowPicks).toHaveBeenCalledWith('short_term', { date: today, limit: 50 });
  });

  it('当日ピックに含まれないポートフォリオ保有銘柄は「保有」バッジで表示する', async () => {
    mockFetchPicks.mockResolvedValue([]);
    mockFetchPortfolio.mockResolvedValue(portfolioSummary([holding({ symbol: '6758', company_name: 'ソニーグループ' })]));

    render(<PickedTickersList selectedSymbol={null} />);

    const link = await screen.findByRole('link', { name: '保有 6758（ソニーグループ）' });
    expect(link).toHaveAttribute('href', '/stock-detail?symbol=6758');
  });

  it('当日ピック済みの銘柄はポートフォリオ保有でも重複表示しない', async () => {
    mockFetchPicks.mockImplementation((horizonType: HorizonType) =>
      Promise.resolve(horizonType === 'mid_term' ? [pick({ symbol: '7203', company_name: 'トヨタ自動車' })] : []),
    );
    mockFetchPortfolio.mockResolvedValue(portfolioSummary([holding({ symbol: '7203', company_name: 'トヨタ自動車' })]));

    render(<PickedTickersList selectedSymbol={null} />);

    expect(await screen.findByRole('link', { name: '公式 7203（トヨタ自動車）' })).toBeInTheDocument();
    expect(screen.queryByRole('link', { name: '保有 7203（トヨタ自動車）' })).not.toBeInTheDocument();
  });

  it('中長期・短期の銘柄を統合し、エンジンバッジ+銘柄コード+社名でリンク表示する', async () => {
    mockFetchPicks.mockImplementation((horizonType: HorizonType) =>
      Promise.resolve(
        horizonType === 'mid_term'
          ? [pick({ symbol: '7203', company_name: 'トヨタ自動車' })]
          : [pick({ symbol: '3441', company_name: '山王', pick_id: 'p2' })],
      ),
    );

    render(<PickedTickersList selectedSymbol="7203" />);

    const link7203 = await screen.findByRole('link', { name: '公式 7203（トヨタ自動車）' });
    expect(link7203).toHaveAttribute('href', '/stock-detail?symbol=7203');
    expect(link7203).toHaveClass('is-active');
    const link3441 = screen.getByRole('link', { name: '公式 3441（山王）' });
    expect(link3441).not.toHaveClass('is-active');
  });

  it('同一銘柄が複数回出る場合は重複排除する', async () => {
    mockFetchPicks.mockResolvedValue([pick({ symbol: '7203' }), pick({ symbol: '7203', pick_id: 'p2' })]);

    render(<PickedTickersList selectedSymbol={null} />);

    expect(await screen.findAllByRole('link', { name: '公式 7203（トヨタ自動車）' })).toHaveLength(1);
  });

  it('公式とシャドウの両方でピックされた銘柄はそれぞれ別に選択可能', async () => {
    mockFetchPicks.mockResolvedValue([pick({ symbol: '9984', company_name: 'ソフトバンクグループ' })]);
    mockFetchShadowPicks.mockResolvedValue([shadowPick({ symbol: '9984', company_name: 'ソフトバンクグループ' })]);

    render(<PickedTickersList selectedSymbol={null} />);

    expect(await screen.findByRole('link', { name: '公式 9984（ソフトバンクグループ）' })).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Gemini 9984（ソフトバンクグループ）' })).toBeInTheDocument();
  });

  it('取得失敗でエラーメッセージを出す', async () => {
    mockFetchPicks.mockRejectedValue(new Error('boom'));

    render(<PickedTickersList selectedSymbol={null} />);

    expect(await screen.findByText('ピック銘柄一覧の取得に失敗しました')).toBeInTheDocument();
  });

  it('アクセシビリティ違反がない', async () => {
    mockFetchPicks.mockResolvedValue([pick({})]);

    const { container } = render(<PickedTickersList selectedSymbol={null} />);
    await screen.findByRole('link');

    expect(await axe(container)).toHaveNoViolations();
  });
});
