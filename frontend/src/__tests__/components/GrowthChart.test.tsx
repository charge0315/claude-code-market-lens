import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { axe } from 'jest-axe';
import { GrowthChart } from '@/components/model-lab/GrowthChart';
import { fetchGrowth } from '@/lib/api/eval';
import type { EvalSnapshot } from '@/lib/api/eval';

jest.mock('@/lib/api/eval');

const mockFetchGrowth = fetchGrowth as jest.MockedFunction<typeof fetchGrowth>;

const SNAPSHOT: EvalSnapshot = {
  snapshot_id: 's1',
  computed_at: '2026-06-01T00:00:00+09:00',
  scope: 'combined',
  model_version: 'v1',
  metric_name: 'win_rate',
  metric_value: 0.55,
  sample_n: 40,
  horizon_days: 20,
  confidence_bucket: null,
};

describe('GrowthChart', () => {
  afterEach(() => {
    jest.clearAllMocks();
  });

  it('データが無ければ案内文を出す', async () => {
    mockFetchGrowth.mockResolvedValue([]);

    render(<GrowthChart />);

    expect(await screen.findByText('データがありません（評価バッチ実行後に表示されます）')).toBeInTheDocument();
  });

  it('scope / 指標を切り替えると再取得する', async () => {
    mockFetchGrowth.mockResolvedValue([SNAPSHOT]);
    const user = userEvent.setup();

    render(<GrowthChart />);
    await waitFor(() => expect(mockFetchGrowth).toHaveBeenCalledWith({ scope: 'combined', metric: 'win_rate', limit: 500 }));

    await user.selectOptions(screen.getByLabelText('scope'), '短期');
    await waitFor(() =>
      expect(mockFetchGrowth).toHaveBeenCalledWith({ scope: 'short_term', metric: 'win_rate', limit: 500 }),
    );
  });

  it('取得失敗でエラーメッセージを出す', async () => {
    mockFetchGrowth.mockRejectedValue(new Error('boom'));

    render(<GrowthChart />);

    expect(await screen.findByText('成長曲線の取得に失敗しました')).toBeInTheDocument();
  });

  it('アクセシビリティ違反がない', async () => {
    mockFetchGrowth.mockResolvedValue([SNAPSHOT]);

    const { container } = render(<GrowthChart />);
    await waitFor(() => expect(mockFetchGrowth).toHaveBeenCalled());

    expect(await axe(container)).toHaveNoViolations();
  });
});
