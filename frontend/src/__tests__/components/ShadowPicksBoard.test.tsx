import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { axe } from 'jest-axe';
import { ShadowPicksBoard } from '@/components/dashboard/ShadowPicksBoard';
import { fetchShadowPicks, fetchPickDetail } from '@/lib/api/picks';
import type { ShadowPickSummary, PickDetail } from '@/lib/api/picks';
import { fetchOhlc } from '@/lib/api/stock';

jest.mock('@/lib/api/picks', () => ({
  ...jest.requireActual('@/lib/api/picks'),
  fetchShadowPicks: jest.fn(),
  fetchPickDetail: jest.fn(),
}));
jest.mock('@/lib/api/stock');

const mockFetchShadowPicks = fetchShadowPicks as jest.MockedFunction<typeof fetchShadowPicks>;
const mockFetchPickDetail = fetchPickDetail as jest.MockedFunction<typeof fetchPickDetail>;
const mockFetchOhlc = fetchOhlc as jest.MockedFunction<typeof fetchOhlc>;

beforeEach(() => {
  mockFetchOhlc.mockResolvedValue({ bars: [], events: [], overlay: null, sub_indicator: null });
});

const PICK_DETAIL: PickDetail = {
  pick_id: 'pick-1',
  run_id: 'run-1',
  issued_at: '2026-09-13T08:25:00+09:00',
  horizon_type: 'mid_term',
  symbol: '7203',
  company_name: 'トヨタ自動車',
  direction: 'bullish',
  entry: 3000,
  stop: 2800,
  target: 3300,
  sub_scores: { technical: 72, trend: 65, fundamental: 50, sentiment: 40 },
  composite_score: 72.5,
  concordance: 0.8,
  confidence_raw: 75,
  confidence: 75,
  confidence_bucket: 'high',
  rationale_struct: { llm_risk_factors: ['金利上昇リスク'], holding_period_days: 10 },
  rationale_text: 'テクニカル・トレンドともに良好で強気の判断根拠が揃っている',
  model_version: 'v1',
  source_contributions: {},
  created_at: '2026-09-13T08:25:01+09:00',
  shadow_predictions: [],
  current_price: 3050,
  change_pct: 1.5,
};

const PICK: ShadowPickSummary = {
  shadow_id: 'shadow-1',
  pick_id: 'pick-1',
  challenger_version: 'gemini:gemini-2.5-pro',
  issued_at: '2026-09-13T08:30:00+09:00',
  horizon_type: 'mid_term',
  symbol: '7203',
  company_name: 'トヨタ自動車',
  direction: 'bullish',
  entry: 3000,
  stop: 2800,
  target: 3300,
  confidence: 68,
  reasoning: 'MACDゴールデンクロスが発生',
  risk_factors: ['総合スコアが中立に近い'],
  holding_period_days: 5,
  current_price: 3050,
  change_pct: 1.5,
  spark: [3000, 3020, 3050],
};

describe('ShadowPicksBoard', () => {
  afterEach(() => {
    jest.clearAllMocks();
  });

  it('シャドウ判定の一覧を表示する', async () => {
    mockFetchShadowPicks.mockResolvedValue([PICK]);

    render(<ShadowPicksBoard />);

    expect(await screen.findByText('7203（トヨタ自動車）')).toBeInTheDocument();
    expect(screen.getByText('強気')).toBeInTheDocument();
    expect(screen.getByText('MACDゴールデンクロスが発生')).toBeInTheDocument();
    expect(screen.getByText('総合スコアが中立に近い')).toBeInTheDocument();
    expect(screen.getAllByText('Gemini')).not.toHaveLength(0);
  });

  it('複数プロバイダのシャドウ判定を行ごとのバッジで区別する', async () => {
    mockFetchShadowPicks.mockResolvedValue([
      PICK,
      { ...PICK, shadow_id: 'shadow-2', symbol: '9984', challenger_version: 'openai:gpt-5.1' },
    ]);

    render(<ShadowPicksBoard />);

    expect(await screen.findByText('7203（トヨタ自動車）')).toBeInTheDocument();
    expect(screen.getAllByText('Gemini')).not.toHaveLength(0);
    expect(screen.getAllByText('ChatGPT')).not.toHaveLength(0);
  });

  it('中長期/短期タブでホライズンを切り替えて再取得する', async () => {
    mockFetchShadowPicks.mockResolvedValue([]);
    const user = userEvent.setup();

    render(<ShadowPicksBoard />);
    await waitFor(() => expect(mockFetchShadowPicks).toHaveBeenCalledWith('mid_term', expect.objectContaining({})));

    await user.click(screen.getByRole('button', { name: '短期' }));
    await waitFor(() => expect(mockFetchShadowPicks).toHaveBeenCalledWith('short_term', expect.objectContaining({})));
  });

  it('pick_idがあれば「公式版と比較」ボタンでピック詳細を開く', async () => {
    mockFetchShadowPicks.mockResolvedValue([PICK]);
    mockFetchPickDetail.mockResolvedValue(PICK_DETAIL);
    const user = userEvent.setup();

    render(<ShadowPicksBoard />);
    await screen.findByText('7203（トヨタ自動車）');

    await user.click(screen.getByRole('button', { name: '公式版と比較' }));
    expect(await screen.findByRole('heading', { name: '公式版のピック詳細' })).toBeInTheDocument();
  });

  it('pick_idが無ければ比較ボタンを出さない', async () => {
    mockFetchShadowPicks.mockResolvedValue([{ ...PICK, pick_id: null }]);

    render(<ShadowPicksBoard />);
    await screen.findByText('7203（トヨタ自動車）');

    expect(screen.queryByRole('button', { name: '公式版と比較' })).not.toBeInTheDocument();
  });

  it('ピックが無ければ空状態メッセージを出す', async () => {
    mockFetchShadowPicks.mockResolvedValue([]);

    render(<ShadowPicksBoard />);

    expect(await screen.findByText('本日のシャドウ判定はまだありません')).toBeInTheDocument();
  });

  it('取得失敗でエラーメッセージを出す', async () => {
    mockFetchShadowPicks.mockRejectedValue(new Error('boom'));

    render(<ShadowPicksBoard />);

    expect(await screen.findByText('シャドウ判定一覧の取得に失敗しました')).toBeInTheDocument();
  });

  it('アクセシビリティ違反がない', async () => {
    mockFetchShadowPicks.mockResolvedValue([PICK]);
    const { container } = render(<ShadowPicksBoard />);
    await screen.findByText('7203（トヨタ自動車）');

    expect(await axe(container)).toHaveNoViolations();
  });
});
