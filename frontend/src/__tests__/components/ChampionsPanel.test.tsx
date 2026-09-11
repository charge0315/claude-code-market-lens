import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { axe } from 'jest-axe';
import { ChampionsPanel } from '@/components/model-lab/ChampionsPanel';
import { applyPromotion, fetchChampions, fetchPromotions } from '@/lib/api/registry';
import type { Champion, Promotion } from '@/lib/api/registry';

jest.mock('@/lib/api/registry');

const mockFetchChampions = fetchChampions as jest.MockedFunction<typeof fetchChampions>;
const mockFetchPromotions = fetchPromotions as jest.MockedFunction<typeof fetchPromotions>;
const mockApplyPromotion = applyPromotion as jest.MockedFunction<typeof applyPromotion>;

const CHAMPION: Champion = {
  lane: 'ml_pool',
  champion_version: 'v3',
  promoted_at: '2026-05-01T00:00:00+09:00',
  promoted_by: 'manual',
};

const PROMOTION: Promotion = {
  promotion_id: 'p1',
  lane: 'ml_pool',
  challenger_version: 'v4',
  champion_version: 'v3',
  evaluated_at: '2026-06-01T00:00:00+09:00',
  holdout_delta: 0.02,
  calib_regressed: 0,
  paper_perf_delta: 0.01,
  paper_days: 20,
  verdict: 'propose_promote',
  applied: 0,
  rationale: '{}',
};

describe('ChampionsPanel', () => {
  afterEach(() => {
    jest.clearAllMocks();
  });

  it('champion 一覧と昇格判定ログを表示する', async () => {
    mockFetchChampions.mockResolvedValue([CHAMPION]);
    mockFetchPromotions.mockResolvedValue([PROMOTION]);

    render(<ChampionsPanel />);

    expect(await screen.findByText('v4')).toBeInTheDocument();
    expect(screen.getByText('昇格提案')).toBeInTheDocument();
    expect(screen.getAllByText('ml_pool')).toHaveLength(2);
    expect(screen.getAllByText('v3')).toHaveLength(2);
  });

  it('propose_promote かつ未適用の判定には適用ボタンが出る', async () => {
    mockFetchChampions.mockResolvedValue([]);
    mockFetchPromotions.mockResolvedValue([PROMOTION]);
    mockApplyPromotion.mockResolvedValue({ promotion_id: 'p1', applied: true });
    const user = userEvent.setup();

    render(<ChampionsPanel />);

    const button = await screen.findByRole('button', { name: '適用' });
    await user.click(button);

    await waitFor(() => expect(mockApplyPromotion).toHaveBeenCalledWith('p1'));
  });

  it('適用済みの判定は「適用済み」と表示しボタンは出さない', async () => {
    mockFetchChampions.mockResolvedValue([]);
    mockFetchPromotions.mockResolvedValue([{ ...PROMOTION, applied: 1 }]);

    render(<ChampionsPanel />);

    expect(await screen.findByText('適用済み')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: '適用' })).not.toBeInTheDocument();
  });

  it('アクセシビリティ違反がない', async () => {
    mockFetchChampions.mockResolvedValue([CHAMPION]);
    mockFetchPromotions.mockResolvedValue([PROMOTION]);

    const { container } = render(<ChampionsPanel />);
    await waitFor(() => expect(mockFetchPromotions).toHaveBeenCalled());

    expect(await axe(container)).toHaveNoViolations();
  });
});
