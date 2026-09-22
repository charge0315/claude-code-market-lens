import { render, screen, waitFor } from '@testing-library/react';
import { axe } from 'jest-axe';
import { PoolPanel } from '@/components/dashboard/PoolPanel';
import { fetchPool } from '@/lib/api/picks';
import type { PoolSummary } from '@/lib/api/picks';

jest.mock('@/lib/api/picks');

const mockFetchPool = fetchPool as jest.MockedFunction<typeof fetchPool>;

function summary(overrides?: Partial<PoolSummary>): PoolSummary {
  return {
    horizon_type: 'mid_term',
    date: '2026-06-01',
    batch_run_id: 'run-1',
    universe_ranking_pool_size: 50,
    pool_limit: 30,
    shortlist_limit: 12,
    max_picks: 10,
    total_candidates: 2,
    shortlisted_count: 1,
    candidates: [
      {
        symbol: '7203',
        company_name: 'トヨタ自動車',
        composite_score: 80.0,
        direction: 'bullish',
        concordance: 0.8,
        score_breakdown: { technical: 70, ml_prediction: 65, fundamental: 55, sentiment: 60 },
        trend_score: 65,
        ml_prediction_rate: 0.62,
        is_shortlisted: true,
      },
      {
        symbol: '6758',
        company_name: 'ソニーグループ',
        composite_score: 40.0,
        direction: 'neutral',
        concordance: 0.3,
        score_breakdown: { technical: 45, ml_prediction: null, fundamental: 40, sentiment: null },
        trend_score: 38,
        ml_prediction_rate: null,
        is_shortlisted: false,
      },
    ],
    ...overrides,
  };
}

describe('PoolPanel', () => {
  afterEach(() => {
    jest.clearAllMocks();
  });

  it('horizonType/date を渡して取得する', async () => {
    mockFetchPool.mockResolvedValue(summary());

    render(<PoolPanel horizonType="mid_term" date="2026-06-01" />);

    await waitFor(() => expect(mockFetchPool).toHaveBeenCalledWith('mid_term', '2026-06-01'));
  });

  it('抽出の経緯（ファネル）を段階ごとの件数で表示する', async () => {
    mockFetchPool.mockResolvedValue(summary());

    render(<PoolPanel horizonType="mid_term" date="2026-06-01" />);

    expect(await screen.findByText('候補プール（上限30）')).toBeInTheDocument();
    expect(screen.getByText('ショートリスト（上限12）')).toBeInTheDocument();
    expect(screen.getByText('最大10')).toBeInTheDocument();
  });

  it('候補一覧をショートリスト進出の有無つきで表示する', async () => {
    mockFetchPool.mockResolvedValue(summary());

    render(<PoolPanel horizonType="mid_term" date="2026-06-01" />);

    expect(await screen.findByText('7203（トヨタ自動車）')).toBeInTheDocument();
    expect(screen.getByText('6758（ソニーグループ）')).toBeInTheDocument();
    expect(screen.getByText('ショートリスト進出')).toBeInTheDocument();
    expect(screen.getByText('候補プール止まり')).toBeInTheDocument();
  });

  it('score_breakdown が null の値は「—」で表示する', async () => {
    mockFetchPool.mockResolvedValue(summary());

    render(<PoolPanel horizonType="mid_term" date="2026-06-01" />);
    await screen.findByText('7203（トヨタ自動車）');

    // 6758 の ml_prediction/sentiment は null。
    const dashes = screen.getAllByText('—');
    expect(dashes.length).toBeGreaterThanOrEqual(2);
  });

  it('候補が空なら案内文を出す', async () => {
    mockFetchPool.mockResolvedValue(summary({ candidates: [], total_candidates: 0, shortlisted_count: 0 }));

    render(<PoolPanel horizonType="mid_term" date="2026-06-01" />);

    expect(await screen.findByText('この日の候補プールデータはまだありません')).toBeInTheDocument();
  });

  it('取得失敗でエラーメッセージを出す', async () => {
    mockFetchPool.mockRejectedValue(new Error('boom'));

    render(<PoolPanel horizonType="mid_term" date="2026-06-01" />);

    expect(await screen.findByText('候補プールの取得に失敗しました')).toBeInTheDocument();
  });

  it('アクセシビリティ違反がない', async () => {
    mockFetchPool.mockResolvedValue(summary());

    const { container } = render(<PoolPanel horizonType="mid_term" date="2026-06-01" />);
    await waitFor(() => expect(mockFetchPool).toHaveBeenCalled());

    expect(await axe(container)).toHaveNoViolations();
  });
});
