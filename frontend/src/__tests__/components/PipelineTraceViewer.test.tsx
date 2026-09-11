import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { axe } from 'jest-axe';
import { PipelineTraceViewer } from '@/components/pipeline/PipelineTraceViewer';
import { fetchRecentRuns, fetchReplay } from '@/lib/api/inference';
import { subscribeSse } from '@/lib/realtime/sse';
import type { RunSummary } from '@/lib/api/inference';

jest.mock('@/lib/api/inference');
jest.mock('@/lib/realtime/sse');

const mockFetchRecentRuns = fetchRecentRuns as jest.MockedFunction<typeof fetchRecentRuns>;
const mockFetchReplay = fetchReplay as jest.MockedFunction<typeof fetchReplay>;
const mockSubscribeSse = subscribeSse as jest.MockedFunction<typeof subscribeSse>;

const RUN: RunSummary = {
  run_id: 'run-1',
  symbol: '7203',
  horizon_type: 'mid_term',
  status: 'done',
  started_at: '2026-06-01T08:50:00+09:00',
  finished_at: '2026-06-01T08:50:04+09:00',
  pick_id: 'pick-1',
};

describe('PipelineTraceViewer', () => {
  afterEach(() => {
    jest.clearAllMocks();
  });

  it('実行が無ければ空状態メッセージを出す', async () => {
    mockFetchRecentRuns.mockResolvedValue([]);
    mockSubscribeSse.mockReturnValue({ close: jest.fn() });

    render(<PipelineTraceViewer />);

    await waitFor(() => expect(mockFetchRecentRuns).toHaveBeenCalled());
    expect(await screen.findByText('まだ推論実行がありません（ピック生成後に表示されます）')).toBeInTheDocument();
  });

  it('実行一覧の取得に成功すると最新の run を自動選択し、ライブ接続する', async () => {
    mockFetchRecentRuns.mockResolvedValue([RUN]);
    mockSubscribeSse.mockReturnValue({ close: jest.fn() });

    render(<PipelineTraceViewer />);

    await waitFor(() =>
      expect(mockSubscribeSse).toHaveBeenCalledWith('/api/inference/run-1/stream', expect.any(Object)),
    );
    expect(screen.getByRole('combobox', { name: '表示する推論実行' })).toBeInTheDocument();
  });

  it('リプレイへ切り替えると保存イベントを取得する', async () => {
    mockFetchRecentRuns.mockResolvedValue([RUN]);
    mockSubscribeSse.mockReturnValue({ close: jest.fn() });
    mockFetchReplay.mockResolvedValue([]);
    const user = userEvent.setup();

    render(<PipelineTraceViewer />);
    await waitFor(() => expect(mockSubscribeSse).toHaveBeenCalled());

    await user.click(screen.getByRole('button', { name: 'リプレイ' }));

    await waitFor(() => expect(mockFetchReplay).toHaveBeenCalledWith('run-1'));
  });

  it('実行一覧の取得失敗でエラーメッセージを出す', async () => {
    mockFetchRecentRuns.mockRejectedValue(new Error('boom'));

    render(<PipelineTraceViewer />);

    expect(await screen.findByText('実行一覧の取得に失敗しました')).toBeInTheDocument();
  });

  it('アクセシビリティ違反がない', async () => {
    mockFetchRecentRuns.mockResolvedValue([RUN]);
    mockSubscribeSse.mockReturnValue({ close: jest.fn() });

    const { container } = render(<PipelineTraceViewer />);
    await waitFor(() => expect(mockSubscribeSse).toHaveBeenCalled());

    expect(await axe(container)).toHaveNoViolations();
  });
});
