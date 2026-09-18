import { render, screen, waitFor } from '@testing-library/react';
import { axe } from 'jest-axe';
import { PitCoveragePanel } from '@/components/model-lab/PitCoveragePanel';
import { fetchPitCoverage } from '@/lib/api/registry';
import type { PitCoverageStatus } from '@/lib/api/registry';

jest.mock('@/lib/api/registry');

const mockFetchPitCoverage = fetchPitCoverage as jest.MockedFunction<typeof fetchPitCoverage>;

const STATUS: PitCoverageStatus = {
  features_enabled: false,
  groups: [
    {
      group: 'pit_fundamental',
      label: 'ファンダメンタル（Vault決算情報）',
      collected_days: 10,
      min_coverage_days: 60,
      remaining_days: 50,
      ready: false,
    },
    {
      group: 'pit_sentiment_keyword',
      label: 'ニュースセンチメント（キーワード判定）',
      collected_days: 60,
      min_coverage_days: 60,
      remaining_days: 0,
      ready: true,
    },
  ],
};

describe('PitCoveragePanel', () => {
  afterEach(() => {
    jest.clearAllMocks();
  });

  it('グループごとの収集進捗を表示する', async () => {
    mockFetchPitCoverage.mockResolvedValue(STATUS);

    render(<PitCoveragePanel />);

    expect(await screen.findByText('ファンダメンタル（Vault決算情報）')).toBeInTheDocument();
    expect(screen.getByText('10 / 60 営業日')).toBeInTheDocument();
    expect(screen.getByText('あと50営業日')).toBeInTheDocument();
    expect(screen.getByText('投入可')).toBeInTheDocument();
    expect(screen.getByText('未有効（PIT_FEATURES_ENABLED=false）')).toBeInTheDocument();
  });

  it('取得失敗でエラーメッセージを出す', async () => {
    mockFetchPitCoverage.mockRejectedValue(new Error('boom'));

    render(<PitCoveragePanel />);

    expect(await screen.findByText('PIT特徴量の収集進捗の取得に失敗しました')).toBeInTheDocument();
  });

  it('アクセシビリティ違反がない', async () => {
    mockFetchPitCoverage.mockResolvedValue(STATUS);

    const { container } = render(<PitCoveragePanel />);
    await waitFor(() => expect(mockFetchPitCoverage).toHaveBeenCalled());

    expect(await axe(container)).toHaveNoViolations();
  });
});
