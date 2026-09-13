import { render, screen } from '@testing-library/react';
import { axe } from 'jest-axe';
import { ModelQualitySummaryLine } from '@/components/model-lab/ModelQualitySummaryLine';
import { fetchQualityDistribution } from '@/lib/api/registry';
import type { QualityDistribution } from '@/lib/api/registry';

jest.mock('@/lib/api/registry');

const mockFetchQualityDistribution = fetchQualityDistribution as jest.MockedFunction<typeof fetchQualityDistribution>;

const DISTRIBUTIONS: QualityDistribution[] = [
  { model_type: 'xgboost', label: 'XGBoost', skill_scores: [0.2, 0.4], rmse_scores: [1.0, 1.2] },
  { model_type: 'random_forest', label: 'RandomForest', skill_scores: [0.3], rmse_scores: [0.8] },
  { model_type: 'lstm', label: 'LSTM', skill_scores: [], rmse_scores: [] },
  { model_type: 'transformer', label: 'Transformer', skill_scores: [], rmse_scores: [] },
];

describe('ModelQualitySummaryLine', () => {
  afterEach(() => {
    jest.clearAllMocks();
  });

  it('全モデルタイプ合算の平均値を1行で表示する', async () => {
    mockFetchQualityDistribution.mockResolvedValue(DISTRIBUTIONS);

    render(<ModelQualitySummaryLine />);

    expect(
      await screen.findByText('champion採用 合計 3銘柄・平均skillスコア 0.300・平均RMSE 1.000'),
    ).toBeInTheDocument();
  });

  it('championが1つも無ければ案内文を出す', async () => {
    mockFetchQualityDistribution.mockResolvedValue([
      { model_type: 'xgboost', label: 'XGBoost', skill_scores: [], rmse_scores: [] },
    ]);

    render(<ModelQualitySummaryLine />);

    expect(
      await screen.findByText('まだ champion がありません（学習・品質ゲート通過後に表示されます）'),
    ).toBeInTheDocument();
  });

  it('取得失敗でエラーメッセージを出す', async () => {
    mockFetchQualityDistribution.mockRejectedValue(new Error('boom'));

    render(<ModelQualitySummaryLine />);

    expect(await screen.findByText('モデル品質分布の取得に失敗しました')).toBeInTheDocument();
  });

  it('アクセシビリティ違反がない', async () => {
    mockFetchQualityDistribution.mockResolvedValue(DISTRIBUTIONS);

    const { container } = render(<ModelQualitySummaryLine />);
    await screen.findByText(/champion採用/);

    expect(await axe(container)).toHaveNoViolations();
  });
});
