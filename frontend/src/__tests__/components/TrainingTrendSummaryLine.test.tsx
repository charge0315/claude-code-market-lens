import { render, screen } from '@testing-library/react';
import { axe } from 'jest-axe';
import { TrainingTrendSummaryLine } from '@/components/model-lab/TrainingTrendSummaryLine';
import { fetchTrainingTrend } from '@/lib/api/registry';
import type { TrainingTrendPoint } from '@/lib/api/registry';

jest.mock('@/lib/api/registry');

const mockFetchTrainingTrend = fetchTrainingTrend as jest.MockedFunction<typeof fetchTrainingTrend>;

const POINTS: TrainingTrendPoint[] = [
  { date: '2026-09-10', model_type: 'xgboost', trained_count: 5, failed_count: 1 },
  { date: '2026-09-10', model_type: 'lstm', trained_count: 3, failed_count: 0 },
  { date: '2026-09-11', model_type: 'xgboost', trained_count: 2, failed_count: 0 },
];

describe('TrainingTrendSummaryLine', () => {
  afterEach(() => {
    jest.clearAllMocks();
  });

  it('直近7日を要求し、合計・1日平均・最新日件数を1行で表示する', async () => {
    mockFetchTrainingTrend.mockResolvedValue(POINTS);

    render(<TrainingTrendSummaryLine />);

    expect(mockFetchTrainingTrend).toHaveBeenCalledWith(7);
    expect(
      await screen.findByText('直近7日合計 10件学習・1日平均 5.0件・最新日（2026-09-11） 2件'),
    ).toBeInTheDocument();
  });

  it('データが無ければ案内文を出す', async () => {
    mockFetchTrainingTrend.mockResolvedValue([]);

    render(<TrainingTrendSummaryLine />);

    expect(
      await screen.findByText('データがありません（銘柄別モデルの学習実行後に表示されます）'),
    ).toBeInTheDocument();
  });

  it('取得失敗でエラーメッセージを出す', async () => {
    mockFetchTrainingTrend.mockRejectedValue(new Error('boom'));

    render(<TrainingTrendSummaryLine />);

    expect(await screen.findByText('学習推移の取得に失敗しました')).toBeInTheDocument();
  });

  it('アクセシビリティ違反がない', async () => {
    mockFetchTrainingTrend.mockResolvedValue(POINTS);

    const { container } = render(<TrainingTrendSummaryLine />);
    await screen.findByText(/直近7日合計/);

    expect(await axe(container)).toHaveNoViolations();
  });
});
