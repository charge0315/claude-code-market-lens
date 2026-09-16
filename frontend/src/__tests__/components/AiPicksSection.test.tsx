import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { AiPicksSection } from '@/components/dashboard/AiPicksSection';
import { fetchPicks, fetchShadowPicks } from '@/lib/api/picks';

jest.mock('@/lib/api/picks', () => ({
  ...jest.requireActual('@/lib/api/picks'),
  fetchPicks: jest.fn().mockResolvedValue([]),
  fetchShadowPicks: jest.fn().mockResolvedValue([]),
  runPicks: jest.fn(),
}));
jest.mock('@/lib/api/stock', () => ({
  fetchStockNote: jest.fn().mockResolvedValue(null),
}));

const mockFetchPicks = fetchPicks as jest.MockedFunction<typeof fetchPicks>;
const mockFetchShadowPicks = fetchShadowPicks as jest.MockedFunction<typeof fetchShadowPicks>;

describe('AiPicksSection', () => {
  afterEach(() => {
    jest.clearAllMocks();
  });

  it('既定では公式のピック一覧を表示する', async () => {
    render(<AiPicksSection />);

    expect(await screen.findByText('本日のピックはまだありません')).toBeInTheDocument();
    expect(mockFetchPicks).toHaveBeenCalled();
    expect(mockFetchShadowPicks).not.toHaveBeenCalled();
  });

  it('シャドウ（比較）タブに切り替えるとシャドウ一覧を表示する', async () => {
    const user = userEvent.setup();
    render(<AiPicksSection />);
    await screen.findByText('本日のピックはまだありません');

    await user.click(screen.getByRole('button', { name: 'シャドウ（比較）' }));

    expect(await screen.findByText('本日のシャドウ判定はまだありません')).toBeInTheDocument();
    expect(mockFetchShadowPicks).toHaveBeenCalled();
  });
});
