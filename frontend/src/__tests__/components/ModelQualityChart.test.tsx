import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { axe } from 'jest-axe';
import { ModelQualityChart } from '@/components/model-lab/ModelQualityChart';
import { fetchQualityDistribution } from '@/lib/api/registry';
import type { QualityDistribution } from '@/lib/api/registry';

jest.mock('@/lib/api/registry');

const mockFetchQualityDistribution = fetchQualityDistribution as jest.MockedFunction<typeof fetchQualityDistribution>;

const DISTRIBUTIONS: QualityDistribution[] = [
  {
    model_type: 'xgboost',
    label: 'XGBoost',
    skill_scores: [0.1, 0.2, 0.3, 0.15, 0.25],
    rmse_scores: [1.0, 1.2, 0.9, 1.1, 1.05],
  },
  { model_type: 'random_forest', label: 'RandomForest', skill_scores: [], rmse_scores: [] },
  { model_type: 'lstm', label: 'LSTM', skill_scores: [], rmse_scores: [] },
  { model_type: 'transformer', label: 'Transformer', skill_scores: [], rmse_scores: [] },
];

describe('ModelQualityChart', () => {
  afterEach(() => {
    jest.clearAllMocks();
  });

  it('championが無いモデルタイプでは案内文を出す（既定はxgboost以外にしないため一度切り替える）', async () => {
    mockFetchQualityDistribution.mockResolvedValue(DISTRIBUTIONS);
    const user = userEvent.setup();

    render(<ModelQualityChart />);
    await waitFor(() => expect(mockFetchQualityDistribution).toHaveBeenCalled());

    await user.selectOptions(screen.getByLabelText('モデルタイプ'), 'RandomForest');

    expect(
      await screen.findByText('このモデルタイプにはまだ champion がありません（学習・品質ゲート通過後に表示されます）'),
    ).toBeInTheDocument();
  });

  it('skillスコアのヒストグラムを表示する', async () => {
    mockFetchQualityDistribution.mockResolvedValue(DISTRIBUTIONS);

    render(<ModelQualityChart />);

    expect(await screen.findByRole('img', { name: 'XGBoost のskillスコア分布' })).toBeInTheDocument();
  });

  it('指標を RMSE に切り替えるとグラフのラベルが変わる', async () => {
    mockFetchQualityDistribution.mockResolvedValue(DISTRIBUTIONS);
    const user = userEvent.setup();

    render(<ModelQualityChart />);
    await screen.findByRole('img', { name: 'XGBoost のskillスコア分布' });

    await user.selectOptions(screen.getByLabelText('指標'), 'RMSE');

    expect(await screen.findByRole('img', { name: 'XGBoost のRMSE分布' })).toBeInTheDocument();
  });

  it('取得失敗でエラーメッセージを出す', async () => {
    mockFetchQualityDistribution.mockRejectedValue(new Error('boom'));

    render(<ModelQualityChart />);

    expect(await screen.findByText('モデル品質分布の取得に失敗しました')).toBeInTheDocument();
  });

  it('アクセシビリティ違反がない', async () => {
    mockFetchQualityDistribution.mockResolvedValue(DISTRIBUTIONS);

    const { container } = render(<ModelQualityChart />);
    await waitFor(() => expect(mockFetchQualityDistribution).toHaveBeenCalled());

    expect(await axe(container)).toHaveNoViolations();
  });
});
