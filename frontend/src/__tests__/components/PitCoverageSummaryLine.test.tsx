import { render, screen, waitFor } from '@testing-library/react';
import { axe } from 'jest-axe';
import { PitCoverageSummaryLine } from '@/components/model-lab/PitCoverageSummaryLine';
import { fetchPitCoverage } from '@/lib/api/registry';
import type { PitCoverageStatus } from '@/lib/api/registry';

jest.mock('@/lib/api/registry');

const mockFetchPitCoverage = fetchPitCoverage as jest.MockedFunction<typeof fetchPitCoverage>;

function statusWith(overrides: Partial<PitCoverageStatus['groups'][number]>): PitCoverageStatus {
  return {
    features_enabled: false,
    groups: [
      {
        group: 'pit_fundamental',
        label: 'ファンダメンタル（Vault決算情報）',
        collected_days: 10,
        min_coverage_days: 60,
        remaining_days: 50,
        ready: false,
        ...overrides,
      },
      {
        group: 'pit_sentiment_keyword',
        label: 'ニュースセンチメント（キーワード判定）',
        collected_days: 0,
        min_coverage_days: 60,
        remaining_days: 60,
        ready: false,
      },
    ],
  };
}

describe('PitCoverageSummaryLine', () => {
  afterEach(() => {
    jest.clearAllMocks();
  });

  it('未収集完了時はあと何営業日かを表示する', async () => {
    mockFetchPitCoverage.mockResolvedValue(statusWith({}));

    render(<PitCoverageSummaryLine />);

    expect(await screen.findByText(/あと50営業日/)).toBeInTheDocument();
  });

  it('収集完了時は完了メッセージを表示する', async () => {
    mockFetchPitCoverage.mockResolvedValue(statusWith({ collected_days: 60, remaining_days: 0, ready: true }));

    render(<PitCoverageSummaryLine />);

    expect(await screen.findByText(/学習に使える状態です/)).toBeInTheDocument();
  });

  it('取得失敗でエラーメッセージを出す', async () => {
    mockFetchPitCoverage.mockRejectedValue(new Error('boom'));

    render(<PitCoverageSummaryLine />);

    expect(await screen.findByText('PIT特徴量の収集進捗の取得に失敗しました')).toBeInTheDocument();
  });

  it('アクセシビリティ違反がない', async () => {
    mockFetchPitCoverage.mockResolvedValue(statusWith({}));

    const { container } = render(<PitCoverageSummaryLine />);
    await waitFor(() => expect(mockFetchPitCoverage).toHaveBeenCalled());

    expect(await axe(container)).toHaveNoViolations();
  });
});
