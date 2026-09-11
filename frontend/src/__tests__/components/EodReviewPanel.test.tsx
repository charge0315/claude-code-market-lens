import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { axe } from 'jest-axe';
import { EodReviewPanel } from '@/components/portfolio/EodReviewPanel';
import { fetchLatestEodReview, runEodReview } from '@/lib/api/portfolio';
import type { EodReview } from '@/lib/api/portfolio';

jest.mock('@/lib/api/portfolio');

const mockFetchLatestEodReview = fetchLatestEodReview as jest.MockedFunction<typeof fetchLatestEodReview>;
const mockRunEodReview = runEodReview as jest.MockedFunction<typeof runEodReview>;

const REVIEW: EodReview = {
  review_date: '2026-06-02',
  created_at: '2026-06-02T16:31:00+09:00',
  summary: '堅調な1日でした。',
  learned_heuristics: [{ heuristic: 'h1', evidence: 'e1', confidence: 0.6 }],
};

describe('EodReviewPanel', () => {
  afterEach(() => {
    jest.clearAllMocks();
  });

  it('レビューが無ければ案内文を出す', async () => {
    mockFetchLatestEodReview.mockResolvedValue(null);

    render(<EodReviewPanel />);

    expect(await screen.findByText('レビューはまだ生成されていません')).toBeInTheDocument();
  });

  it('レビューの要約と教訓を表示する', async () => {
    mockFetchLatestEodReview.mockResolvedValue(REVIEW);

    render(<EodReviewPanel />);

    expect(await screen.findByText('堅調な1日でした。')).toBeInTheDocument();
    expect(screen.getByText('h1')).toBeInTheDocument();
    expect(screen.getByText('確信度 60%')).toBeInTheDocument();
  });

  it('本日分を実行ボタンで手動実行する', async () => {
    mockFetchLatestEodReview.mockResolvedValue(null);
    mockRunEodReview.mockResolvedValue(REVIEW);
    const user = userEvent.setup();

    render(<EodReviewPanel />);
    await waitFor(() => expect(mockFetchLatestEodReview).toHaveBeenCalled());

    await user.click(screen.getByRole('button', { name: '本日分を実行' }));

    expect(await screen.findByText('堅調な1日でした。')).toBeInTheDocument();
  });

  it('取得失敗でエラーメッセージを出す', async () => {
    mockFetchLatestEodReview.mockRejectedValue(new Error('boom'));

    render(<EodReviewPanel />);

    expect(await screen.findByText('大引け後レビューの取得に失敗しました')).toBeInTheDocument();
  });

  it('アクセシビリティ違反がない', async () => {
    mockFetchLatestEodReview.mockResolvedValue(REVIEW);

    const { container } = render(<EodReviewPanel />);
    await waitFor(() => expect(mockFetchLatestEodReview).toHaveBeenCalled());

    expect(await axe(container)).toHaveNoViolations();
  });
});
