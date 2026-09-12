import { render, screen, waitFor } from '@testing-library/react';
import { axe } from 'jest-axe';
import { StockOverview } from '@/components/stock-detail/StockOverview';
import { fetchRecentRuns } from '@/lib/api/inference';
import { fetchPickDetail } from '@/lib/api/picks';
import { fetchOhlc } from '@/lib/api/stock';
import type { RunSummary } from '@/lib/api/inference';
import type { PickDetail } from '@/lib/api/picks';

jest.mock('@/lib/api/inference');
jest.mock('@/lib/api/picks');
jest.mock('@/lib/api/stock');

const mockFetchRecentRuns = fetchRecentRuns as jest.MockedFunction<typeof fetchRecentRuns>;
const mockFetchPickDetail = fetchPickDetail as jest.MockedFunction<typeof fetchPickDetail>;
const mockFetchOhlc = fetchOhlc as jest.MockedFunction<typeof fetchOhlc>;

const RUN: RunSummary = {
  run_id: 'run-1',
  symbol: '7203',
  horizon_type: 'mid_term',
  status: 'done',
  started_at: '2026-06-01T08:50:00+09:00',
  finished_at: '2026-06-01T08:50:04+09:00',
  pick_id: 'pick-1',
};

const PICK: PickDetail = {
  pick_id: 'pick-1',
  run_id: 'run-1',
  issued_at: '2026-06-01T08:50:00+09:00',
  horizon_type: 'mid_term',
  symbol: '7203',
  company_name: 'トヨタ自動車',
  direction: 'bullish',
  entry: 1000,
  stop: 950,
  target: 1100,
  sub_scores: { technical: 72, trend: 65, fundamental: 50, sentiment: 40 },
  composite_score: 60,
  concordance: 0.8,
  confidence_raw: 75,
  confidence: 75,
  confidence_bucket: 'high',
  rationale_struct: {},
  rationale_text: 'テクニカルとトレンドが良好',
  model_version: 'test-model',
  source_contributions: {},
  created_at: '2026-06-01T08:50:01+09:00',
  shadow_predictions: [],
  current_price: null,
  change_pct: null,
};

describe('StockOverview', () => {
  afterEach(() => {
    jest.clearAllMocks();
  });

  it('実行が無ければ案内文を出す', async () => {
    mockFetchRecentRuns.mockResolvedValue([]);

    render(<StockOverview />);

    expect(await screen.findByText('まだ推論実行がありません（ピック生成後に表示されます）')).toBeInTheDocument();
  });

  it('直近の実行の銘柄でチャートと4分析内訳を表示する', async () => {
    mockFetchRecentRuns.mockResolvedValue([RUN]);
    mockFetchPickDetail.mockResolvedValue(PICK);
    mockFetchOhlc.mockResolvedValue([]);

    render(<StockOverview />);

    expect(await screen.findByText('7203')).toBeInTheDocument();
    await waitFor(() => expect(mockFetchPickDetail).toHaveBeenCalledWith('pick-1'));
    expect(await screen.findByText('テクニカルとトレンドが良好')).toBeInTheDocument();
  });

  it('取得失敗でエラーメッセージを出す', async () => {
    mockFetchRecentRuns.mockRejectedValue(new Error('boom'));

    render(<StockOverview />);

    expect(await screen.findByText('直近の実行の取得に失敗しました')).toBeInTheDocument();
  });

  it('アクセシビリティ違反がない', async () => {
    mockFetchRecentRuns.mockResolvedValue([RUN]);
    mockFetchPickDetail.mockResolvedValue(PICK);
    mockFetchOhlc.mockResolvedValue([]);

    const { container } = render(<StockOverview />);
    await waitFor(() => expect(mockFetchPickDetail).toHaveBeenCalled());

    expect(await axe(container)).toHaveNoViolations();
  });
});
