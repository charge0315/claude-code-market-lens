import { render, screen } from '@testing-library/react';
import { axe } from 'jest-axe';
import { PickedTickersList } from '@/components/stock-detail/PickedTickersList';
import { fetchGeminiPicks, fetchPicks } from '@/lib/api/picks';
import type { GeminiPickSummary, PickSummary } from '@/lib/api/picks';

jest.mock('@/lib/api/picks');

const mockFetchPicks = fetchPicks as jest.MockedFunction<typeof fetchPicks>;
const mockFetchGeminiPicks = fetchGeminiPicks as jest.MockedFunction<typeof fetchGeminiPicks>;

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

function geminiPick(overrides: Partial<GeminiPickSummary>): GeminiPickSummary {
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
    mockFetchGeminiPicks.mockResolvedValue([]);
  });

  afterEach(() => {
    jest.clearAllMocks();
  });

  it('ピックが無ければ案内文を出す', async () => {
    mockFetchPicks.mockResolvedValue([]);

    render(<PickedTickersList selectedSymbol={null} />);

    expect(await screen.findByText('ピックされた銘柄はまだありません')).toBeInTheDocument();
  });

  it('中長期・短期の銘柄を統合し、エンジンバッジ+銘柄コード+社名でリンク表示する', async () => {
    mockFetchPicks.mockImplementation((horizonType) =>
      Promise.resolve(
        horizonType === 'mid_term'
          ? [pick({ symbol: '7203', company_name: 'トヨタ自動車' })]
          : [pick({ symbol: '3441', company_name: '山王', pick_id: 'p2' })],
      ),
    );

    render(<PickedTickersList selectedSymbol="7203" />);

    const link7203 = await screen.findByRole('link', { name: 'Claude 7203（トヨタ自動車）' });
    expect(link7203).toHaveAttribute('href', '/stock-detail?symbol=7203');
    expect(link7203).toHaveClass('is-active');
    const link3441 = screen.getByRole('link', { name: 'Claude 3441（山王）' });
    expect(link3441).not.toHaveClass('is-active');
  });

  it('同一銘柄が複数回出る場合は重複排除する', async () => {
    mockFetchPicks.mockResolvedValue([pick({ symbol: '7203' }), pick({ symbol: '7203', pick_id: 'p2' })]);

    render(<PickedTickersList selectedSymbol={null} />);

    expect(await screen.findAllByRole('link', { name: 'Claude 7203（トヨタ自動車）' })).toHaveLength(1);
  });

  it('Claude と Gemini の両方でピックされた銘柄はそれぞれ別に選択可能', async () => {
    mockFetchPicks.mockResolvedValue([pick({ symbol: '9984', company_name: 'ソフトバンクグループ' })]);
    mockFetchGeminiPicks.mockResolvedValue([geminiPick({ symbol: '9984', company_name: 'ソフトバンクグループ' })]);

    render(<PickedTickersList selectedSymbol={null} />);

    expect(await screen.findByRole('link', { name: 'Claude 9984（ソフトバンクグループ）' })).toBeInTheDocument();
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
