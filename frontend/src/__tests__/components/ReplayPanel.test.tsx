import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { axe } from 'jest-axe';
import { ReplayPanel } from '@/components/model-lab/ReplayPanel';
import {
  fetchReplayDetail,
  fetchReplayRuns,
  resumeReplay,
  startReplay,
  stopReplay,
  type ReplayDetail,
  type ReplayRun,
} from '@/lib/api/replay';
import { ApiError } from '@/lib/api/client';

jest.mock('@/lib/api/replay');

const mockRuns = fetchReplayRuns as jest.MockedFunction<typeof fetchReplayRuns>;
const mockDetail = fetchReplayDetail as jest.MockedFunction<typeof fetchReplayDetail>;
const mockStart = startReplay as jest.MockedFunction<typeof startReplay>;
const mockStop = stopReplay as jest.MockedFunction<typeof stopReplay>;
const mockResume = resumeReplay as jest.MockedFunction<typeof resumeReplay>;

const RUN: ReplayRun = {
  run_id: '11111111-1111-1111-1111-111111111111',
  status: 'running',
  start_date: '2022-01-04',
  end_date: '2022-12-30',
  cursor_date: '2022-07-01',
  error: null,
  summary: null,
  heartbeat_at: '2026-09-23T10:00:00+09:00',
  created_at: '2026-09-23T09:00:00+09:00',
  is_alive: true,
};

function detailOf(run: ReplayRun): ReplayDetail {
  return {
    run,
    pick_counts: { short_term: 700, mid_term: 1100 },
    retrains: [
      {
        trained_on: '2022-06-01',
        model_version: 'replay-pool@2022-06-01',
        metrics: { auc: 0.553 },
      },
    ],
    live: {
      short_term: {
        horizon_days: 3,
        performance: {
          n: 640,
          win_rate: 0.512,
          avg_excess: 0.0021,
          hit_target_rate: 0.2,
        },
      },
      mid_term: { horizon_days: 20, performance: { n: 0 } },
    },
  };
}

describe('ReplayPanel', () => {
  afterEach(() => {
    jest.clearAllMocks();
  });

  it('実行履歴がなければ説明と開始ボタンを出し、期間省略で開始できる', async () => {
    mockRuns.mockResolvedValue([]);
    mockStart.mockResolvedValue({ run_id: RUN.run_id });
    const user = userEvent.setup();

    render(<ReplayPanel />);

    await user.click(await screen.findByRole('button', { name: 'リプレイを開始' }));
    expect(mockStart).toHaveBeenCalledWith({});
  });

  it('期間を指定して開始できる', async () => {
    mockRuns.mockResolvedValue([]);
    mockStart.mockResolvedValue({ run_id: RUN.run_id });
    const user = userEvent.setup();

    render(<ReplayPanel />);
    await user.type(await screen.findByLabelText('開始日'), '2022-01-04');
    await user.type(screen.getByLabelText('終了日'), '2022-12-30');
    await user.click(screen.getByRole('button', { name: 'リプレイを開始' }));

    expect(mockStart).toHaveBeenCalledWith({
      start_date: '2022-01-04',
      end_date: '2022-12-30',
    });
  });

  it('実行中は進捗・途中成績・停止ボタンを表示する', async () => {
    mockRuns.mockResolvedValue([RUN]);
    mockDetail.mockResolvedValue(detailOf(RUN));
    mockStop.mockResolvedValue({ run_id: RUN.run_id, status: 'stopping' });
    const user = userEvent.setup();

    render(<ReplayPanel />);

    expect(await screen.findByText('実行中')).toBeInTheDocument();
    expect(screen.getByRole('progressbar')).toHaveAttribute('aria-valuenow', '49');
    expect(screen.getByText('51.2%')).toBeInTheDocument();
    expect(screen.getByText('+0.21%')).toHaveClass('gain');
    expect(screen.queryByRole('button', { name: 'リプレイを開始' })).not.toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: '停止' }));
    expect(mockStop).toHaveBeenCalledWith(RUN.run_id);
  });

  it('停止・失敗したリプレイは続きから再開できる', async () => {
    const failed: ReplayRun = {
      ...RUN,
      status: 'failed',
      is_alive: false,
      error: 'JQuantsError: boom',
    };
    mockRuns.mockResolvedValue([failed]);
    mockDetail.mockResolvedValue(detailOf(failed));
    mockResume.mockResolvedValue({ run_id: RUN.run_id, status: 'pending' });
    const user = userEvent.setup();

    render(<ReplayPanel />);

    expect(await screen.findByText(/JQuantsError: boom/)).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: '続きから再開' }));
    expect(mockResume).toHaveBeenCalledWith(RUN.run_id);
  });

  it('完了後は較正表・ファクター IC・challenger を表示する', async () => {
    const done: ReplayRun = {
      ...RUN,
      status: 'completed',
      is_alive: false,
      cursor_date: RUN.end_date,
      summary: {
        horizons: {
          short_term: {
            '3': {
              performance: { n: 900, win_rate: 0.52 },
              calibration_table: [{ bucket_low: 60, bucket_high: 65, n: 120, win_rate: 0.55 }],
              factor_ics: {
                composite: 0.031,
                technical: 0.028,
                ml_prediction: 0.041,
                fundamental: null,
                sentiment: null,
                trend: -0.01,
              },
            },
          },
          mid_term: {},
        },
        ic_weights: {
          short_term: {
            technical: 0.4,
            ml_prediction: 0.3,
            fundamental: 0.2,
            sentiment: 0.1,
          },
          mid_term: {},
        },
        calibration: {
          short_term: { horizon_days: 3, n: 900, method: 'isotonic' },
          mid_term: { horizon_days: 20, n: 0, method: 'identity' },
        },
        challenger_version: 'replay-11111111-2022-12-30',
      },
    };
    mockRuns.mockResolvedValue([done]);
    mockDetail.mockResolvedValue(detailOf(done));

    render(<ReplayPanel />);

    expect(await screen.findByText('完了')).toBeInTheDocument();
    expect(screen.getByText('60〜65')).toBeInTheDocument();
    expect(screen.getByText('55.0%')).toBeInTheDocument();
    expect(screen.getByText('0.041')).toBeInTheDocument();
    expect(screen.getByText(/replay-11111111-2022-12-30/)).toBeInTheDocument();
    // 完了後は新しいリプレイを始められる
    expect(screen.getByRole('button', { name: 'リプレイを開始' })).toBeInTheDocument();
  });

  it('開始に失敗したらサーバのメッセージを表示する', async () => {
    mockRuns.mockResolvedValue([]);
    mockStart.mockRejectedValue(new ApiError('開始日は終了日より前にしてください', 200));
    const user = userEvent.setup();

    render(<ReplayPanel />);
    await user.click(await screen.findByRole('button', { name: 'リプレイを開始' }));

    expect(await screen.findByRole('alert')).toHaveTextContent('開始日は終了日より前にしてください');
  });

  it('アクセシビリティ違反がない', async () => {
    mockRuns.mockResolvedValue([RUN]);
    mockDetail.mockResolvedValue(detailOf(RUN));

    const { container } = render(<ReplayPanel />);
    await waitFor(() => expect(screen.getByText('実行中')).toBeInTheDocument());

    expect(await axe(container)).toHaveNoViolations();
  });
});
