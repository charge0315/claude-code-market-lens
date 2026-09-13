import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { AiPicksSection } from '@/components/dashboard/AiPicksSection';
import { fetchGeminiPicks, fetchPicks } from '@/lib/api/picks';

jest.mock('@/lib/api/picks', () => ({
  ...jest.requireActual('@/lib/api/picks'),
  fetchPicks: jest.fn().mockResolvedValue([]),
  fetchGeminiPicks: jest.fn().mockResolvedValue([]),
  runPicks: jest.fn(),
}));
jest.mock('@/lib/api/stock', () => ({
  fetchStockNote: jest.fn().mockResolvedValue(null),
}));

const mockFetchPicks = fetchPicks as jest.MockedFunction<typeof fetchPicks>;
const mockFetchGeminiPicks = fetchGeminiPicks as jest.MockedFunction<typeof fetchGeminiPicks>;

describe('AiPicksSection', () => {
  afterEach(() => {
    jest.clearAllMocks();
  });

  it('既定ではClaude（公式）のピック一覧を表示する', async () => {
    render(<AiPicksSection />);

    expect(await screen.findByText('本日のピックはまだありません')).toBeInTheDocument();
    expect(mockFetchPicks).toHaveBeenCalled();
    expect(mockFetchGeminiPicks).not.toHaveBeenCalled();
  });

  it('Gemini（比較）タブに切り替えるとGemini一覧を表示する', async () => {
    const user = userEvent.setup();
    render(<AiPicksSection />);
    await screen.findByText('本日のピックはまだありません');

    await user.click(screen.getByRole('button', { name: 'Gemini（比較）' }));

    expect(await screen.findByText('本日のGemini判定はまだありません')).toBeInTheDocument();
    expect(mockFetchGeminiPicks).toHaveBeenCalled();
  });
});
