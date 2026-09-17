import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { axe } from 'jest-axe';
import { AiPickSelector } from '@/components/portfolio/AiPickSelector';
import { fetchPicks, fetchShadowPicks } from '@/lib/api/picks';
import type { PickSummary, ShadowPickSummary, HorizonType } from '@/lib/api/picks';

jest.mock('@/lib/api/picks');

const mockFetchPicks = fetchPicks as jest.MockedFunction<typeof fetchPicks>;
const mockFetchShadowPicks = fetchShadowPicks as jest.MockedFunction<typeof fetchShadowPicks>;

function pick(overrides: Partial<PickSummary>): PickSummary {
  return {
    pick_id: 'p1',
    issued_at: '2026-09-13T08:50:00+09:00',
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
    issued_at: '2026-09-13T08:50:00+09:00',
    horizon_type: 'mid_term',
    symbol: '9984',
    company_name: 'ソフトバンクグループ',
    direction: 'bullish',
    entry: 2000,
    stop: 1900,
    target: 2200,
    confidence: 65,
    reasoning: null,
    risk_factors: [],
    holding_period_days: null,
    current_price: null,
    change_pct: null,
    spark: [],
    ...overrides,
  };
}

describe('AiPickSelector', () => {
  afterEach(() => {
    jest.clearAllMocks();
  });

  it('本日の公式/シャドウ両方のピックを選択肢として表示する', async () => {
    mockFetchPicks.mockImplementation((horizonType: HorizonType) =>
      Promise.resolve(horizonType === 'mid_term' ? [pick({ symbol: '7203' })] : []),
    );
    mockFetchShadowPicks.mockImplementation((horizonType: HorizonType) =>
      Promise.resolve(horizonType === 'mid_term' ? [shadowPick({ symbol: '9984' })] : []),
    );

    render(<AiPickSelector onSelect={jest.fn()} />);

    expect(await screen.findByRole('button', { name: /公式.*7203（トヨタ自動車）.*¥1,000/ })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Gemini.*9984（ソフトバンクグループ）.*¥2,000/ })).toBeInTheDocument();
  });

  it('選択すると onSelect が entry 付きで呼ばれる', async () => {
    mockFetchPicks.mockResolvedValue([pick({ symbol: '7203', entry: 1234 })]);
    mockFetchShadowPicks.mockResolvedValue([]);
    const onSelect = jest.fn();
    const user = userEvent.setup();

    render(<AiPickSelector onSelect={onSelect} />);
    await user.click(await screen.findByRole('button', { name: /7203/ }));

    expect(onSelect).toHaveBeenCalledWith({
      symbol: '7203',
      companyName: 'トヨタ自動車',
      engine: 'official',
      entry: 1234,
    });
  });

  it('本日のピックが無ければ案内文を出す', async () => {
    mockFetchPicks.mockResolvedValue([]);
    mockFetchShadowPicks.mockResolvedValue([]);

    render(<AiPickSelector onSelect={jest.fn()} />);

    expect(await screen.findByText('本日のAIピックはまだありません')).toBeInTheDocument();
  });

  it('取得失敗でエラーメッセージを出す', async () => {
    mockFetchPicks.mockRejectedValue(new Error('boom'));
    mockFetchShadowPicks.mockResolvedValue([]);

    render(<AiPickSelector onSelect={jest.fn()} />);

    expect(await screen.findByText('本日のAIピック一覧の取得に失敗しました')).toBeInTheDocument();
  });

  it('アクセシビリティ違反がない', async () => {
    mockFetchPicks.mockResolvedValue([pick({})]);
    mockFetchShadowPicks.mockResolvedValue([]);

    const { container } = render(<AiPickSelector onSelect={jest.fn()} />);
    await screen.findByRole('button');

    expect(await axe(container)).toHaveNoViolations();
  });
});
