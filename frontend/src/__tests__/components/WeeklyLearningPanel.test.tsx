import { render, screen, waitFor } from '@testing-library/react';
import { axe } from 'jest-axe';
import { WeeklyLearningPanel } from '@/components/model-lab/WeeklyLearningPanel';
import { fetchWeeklyLearning } from '@/lib/api/eval';
import type { WeeklyLearningSummary } from '@/lib/api/eval';

jest.mock('@/lib/api/eval');

const mockFetchWeeklyLearning = fetchWeeklyLearning as jest.MockedFunction<typeof fetchWeeklyLearning>;

const SUMMARY: WeeklyLearningSummary = {
  window_days: 7,
  as_of: '2026-06-08T00:00:00+09:00',
  metric_deltas: [{ scope: 'combined', metric: 'win_rate', before: 0.5, after: 0.55, delta: 0.05, before_at: '', after_at: '' }],
  recent_promotions: [{}],
  recent_drift_flags: [],
};

describe('WeeklyLearningPanel', () => {
  afterEach(() => {
    jest.clearAllMocks();
  });

  it('指標差分と件数サマリを表示する', async () => {
    mockFetchWeeklyLearning.mockResolvedValue(SUMMARY);

    render(<WeeklyLearningPanel />);

    expect(await screen.findByText('combined / win_rate')).toBeInTheDocument();
    expect(screen.getByText('直近の昇格判定: 1 件')).toBeInTheDocument();
    expect(screen.getByText('直近のドリフト検知: 0 件')).toBeInTheDocument();
  });

  it('データが無ければ案内文を出す', async () => {
    mockFetchWeeklyLearning.mockResolvedValue({ ...SUMMARY, metric_deltas: [] });

    render(<WeeklyLearningPanel />);

    expect(await screen.findByText('指標の変化はまだありません')).toBeInTheDocument();
  });

  it('取得失敗でエラーメッセージを出す', async () => {
    mockFetchWeeklyLearning.mockRejectedValue(new Error('boom'));

    render(<WeeklyLearningPanel />);

    expect(await screen.findByText('週次学習差分の取得に失敗しました')).toBeInTheDocument();
  });

  it('アクセシビリティ違反がない', async () => {
    mockFetchWeeklyLearning.mockResolvedValue(SUMMARY);

    const { container } = render(<WeeklyLearningPanel />);
    await waitFor(() => expect(mockFetchWeeklyLearning).toHaveBeenCalled());

    expect(await axe(container)).toHaveNoViolations();
  });
});
