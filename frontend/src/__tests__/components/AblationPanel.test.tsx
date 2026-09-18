import { render, screen, waitFor } from '@testing-library/react';
import { axe } from 'jest-axe';
import { AblationPanel } from '@/components/model-lab/AblationPanel';
import { fetchAblations } from '@/lib/api/registry';
import type { SourceAblationEntry } from '@/lib/api/registry';

jest.mock('@/lib/api/registry');

const mockFetchAblations = fetchAblations as jest.MockedFunction<typeof fetchAblations>;

const ENTRY: SourceAblationEntry = {
  ablation_id: 'a1',
  computed_at: '2026-09-18T04:00:00+09:00',
  quarter: '2026Q3',
  excluded_source: 'pit_fundamental',
  metric_name: 'auc',
  metric_delta: -0.03,
  sample_n: 120,
};

describe('AblationPanel', () => {
  afterEach(() => {
    jest.clearAllMocks();
  });

  it('アブレーション結果を表示する', async () => {
    mockFetchAblations.mockResolvedValue([ENTRY]);

    render(<AblationPanel />);

    expect(await screen.findByText('ファンダメンタル（Vault決算情報）')).toBeInTheDocument();
    expect(screen.getByText('AUC')).toBeInTheDocument();
    expect(screen.getByText('-0.0300')).toBeInTheDocument();
  });

  it('データが無ければ空メッセージを出す', async () => {
    mockFetchAblations.mockResolvedValue([]);

    render(<AblationPanel />);

    expect(await screen.findByText(/アブレーション評価はまだありません/)).toBeInTheDocument();
  });

  it('取得失敗でエラーメッセージを出す', async () => {
    mockFetchAblations.mockRejectedValue(new Error('boom'));

    render(<AblationPanel />);

    expect(await screen.findByText('ソースアブレーション評価の取得に失敗しました')).toBeInTheDocument();
  });

  it('アクセシビリティ違反がない', async () => {
    mockFetchAblations.mockResolvedValue([ENTRY]);

    const { container } = render(<AblationPanel />);
    await waitFor(() => expect(mockFetchAblations).toHaveBeenCalled());

    expect(await axe(container)).toHaveNoViolations();
  });
});
