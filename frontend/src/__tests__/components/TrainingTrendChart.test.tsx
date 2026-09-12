import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { axe } from 'jest-axe';
import { TrainingTrendChart } from '@/components/model-lab/TrainingTrendChart';
import { fetchTrainingTrend } from '@/lib/api/registry';
import type { TrainingTrendPoint } from '@/lib/api/registry';

jest.mock('@/lib/api/registry');

const mockFetchTrainingTrend = fetchTrainingTrend as jest.MockedFunction<typeof fetchTrainingTrend>;

const POINTS: TrainingTrendPoint[] = [
  { date: '2026-09-10', model_type: 'xgboost', trained_count: 5, failed_count: 1 },
  { date: '2026-09-11', model_type: 'lstm', trained_count: 2, failed_count: 0 },
];

describe('TrainingTrendChart', () => {
  afterEach(() => {
    jest.clearAllMocks();
  });

  it('データが無ければ案内文を出す', async () => {
    mockFetchTrainingTrend.mockResolvedValue([]);

    render(<TrainingTrendChart />);

    expect(
      await screen.findByText('データがありません（銘柄別モデルの学習実行後に表示されます）'),
    ).toBeInTheDocument();
  });

  it('学習推移のグラフを表示する', async () => {
    mockFetchTrainingTrend.mockResolvedValue(POINTS);

    render(<TrainingTrendChart />);

    expect(await screen.findByRole('img', { name: '日別・モデルタイプ別の学習件数の推移' })).toBeInTheDocument();
  });

  it('期間を切り替えると再取得する', async () => {
    mockFetchTrainingTrend.mockResolvedValue(POINTS);
    const user = userEvent.setup();

    render(<TrainingTrendChart />);
    await waitFor(() => expect(mockFetchTrainingTrend).toHaveBeenCalledWith(30));

    await user.selectOptions(screen.getByLabelText('期間'), '直近7日');
    await waitFor(() => expect(mockFetchTrainingTrend).toHaveBeenCalledWith(7));
  });

  it('取得失敗でエラーメッセージを出す', async () => {
    mockFetchTrainingTrend.mockRejectedValue(new Error('boom'));

    render(<TrainingTrendChart />);

    expect(await screen.findByText('学習推移の取得に失敗しました')).toBeInTheDocument();
  });

  it('アクセシビリティ違反がない', async () => {
    mockFetchTrainingTrend.mockResolvedValue(POINTS);

    const { container } = render(<TrainingTrendChart />);
    await waitFor(() => expect(mockFetchTrainingTrend).toHaveBeenCalled());

    expect(await axe(container)).toHaveNoViolations();
  });
});
