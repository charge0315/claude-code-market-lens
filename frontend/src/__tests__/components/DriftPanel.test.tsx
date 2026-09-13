import { render, screen, waitFor } from '@testing-library/react';
import { axe } from 'jest-axe';
import { DriftPanel } from '@/components/model-lab/DriftPanel';
import { fetchDrift } from '@/lib/api/registry';
import type { DriftSnapshot } from '@/lib/api/registry';

jest.mock('@/lib/api/registry');

const mockFetchDrift = fetchDrift as jest.MockedFunction<typeof fetchDrift>;

const SNAPSHOT: DriftSnapshot = {
  drift_id: 'd1',
  computed_at: '2026-06-01T00:00:00+09:00',
  feature_name: 'technical.rsi',
  psi: 0.25,
  baseline_window: '2026-03-01/2026-04-30',
  current_window: '2026-05-01/2026-05-31',
  drift_flag: 1,
  triggered_retrain: 0,
};

describe('DriftPanel', () => {
  afterEach(() => {
    jest.clearAllMocks();
  });

  it('ドリフト検知された特徴量を表示する', async () => {
    mockFetchDrift.mockResolvedValue([SNAPSHOT]);

    render(<DriftPanel />);

    // 特徴量ごとの直近状態サマリ（バー表示）と全履歴テーブルの両方に出るため複数マッチになる。
    expect((await screen.findAllByText('technical.rsi')).length).toBeGreaterThan(0);
    expect(screen.getByText('要再学習')).toBeInTheDocument();
    expect(screen.getByText('ドリフト検知')).toBeInTheDocument();
  });

  it('データが無ければ空メッセージを出す', async () => {
    mockFetchDrift.mockResolvedValue([]);

    render(<DriftPanel />);

    expect(await screen.findByText('ドリフト計測はまだありません')).toBeInTheDocument();
  });

  it('取得失敗でエラーメッセージを出す', async () => {
    mockFetchDrift.mockRejectedValue(new Error('boom'));

    render(<DriftPanel />);

    expect(await screen.findByText('ドリフト履歴の取得に失敗しました')).toBeInTheDocument();
  });

  it('アクセシビリティ違反がない', async () => {
    mockFetchDrift.mockResolvedValue([SNAPSHOT]);

    const { container } = render(<DriftPanel />);
    await waitFor(() => expect(mockFetchDrift).toHaveBeenCalled());

    expect(await axe(container)).toHaveNoViolations();
  });
});
