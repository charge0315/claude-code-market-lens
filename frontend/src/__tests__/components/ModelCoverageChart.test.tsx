import { render, screen, waitFor } from '@testing-library/react';
import { axe } from 'jest-axe';
import { ModelCoverageChart } from '@/components/model-lab/ModelCoverageChart';
import { fetchModelCoverage } from '@/lib/api/registry';
import type { ModelCoverage } from '@/lib/api/registry';

jest.mock('@/lib/api/registry');

const mockFetchModelCoverage = fetchModelCoverage as jest.MockedFunction<typeof fetchModelCoverage>;

const COVERAGE: ModelCoverage[] = [
  { model_type: 'xgboost', label: 'XGBoost', universe_size: 4000, trained_count: 2000, champion_count: 1500 },
  { model_type: 'random_forest', label: 'RandomForest', universe_size: 4000, trained_count: 0, champion_count: 0 },
  { model_type: 'lstm', label: 'LSTM', universe_size: 4000, trained_count: 0, champion_count: 0 },
  { model_type: 'transformer', label: 'Transformer', universe_size: 4000, trained_count: 0, champion_count: 0 },
];

describe('ModelCoverageChart', () => {
  afterEach(() => {
    jest.clearAllMocks();
  });

  it('学習実績が無ければ案内文を出す', async () => {
    mockFetchModelCoverage.mockResolvedValue(
      COVERAGE.map((c) => ({ ...c, trained_count: 0, champion_count: 0 })),
    );

    render(<ModelCoverageChart />);

    expect(
      await screen.findByText('データがありません（銘柄別モデルの学習実行後に表示されます）'),
    ).toBeInTheDocument();
  });

  it('モデルタイプごとにリングと学習件数を表示する', async () => {
    mockFetchModelCoverage.mockResolvedValue(COVERAGE);

    render(<ModelCoverageChart />);

    expect(
      await screen.findByRole('img', {
        name: 'XGBoost: 学習済み 2000/4000銘柄（50%）、うち champion採用 1500銘柄（37.5%）',
      }),
    ).toBeInTheDocument();
    expect(screen.getByText('学習済み 2000/4000')).toBeInTheDocument();
    expect(screen.getByText('champion 1500銘柄')).toBeInTheDocument();
  });

  it('取得失敗でエラーメッセージを出す', async () => {
    mockFetchModelCoverage.mockRejectedValue(new Error('boom'));

    render(<ModelCoverageChart />);

    expect(await screen.findByText('学習カバレッジの取得に失敗しました')).toBeInTheDocument();
  });

  it('アクセシビリティ違反がない', async () => {
    mockFetchModelCoverage.mockResolvedValue(COVERAGE);

    const { container } = render(<ModelCoverageChart />);
    await waitFor(() => expect(mockFetchModelCoverage).toHaveBeenCalled());

    expect(await axe(container)).toHaveNoViolations();
  });
});
