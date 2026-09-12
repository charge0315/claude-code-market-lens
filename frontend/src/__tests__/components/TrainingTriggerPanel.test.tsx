import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { axe } from 'jest-axe';
import { TrainingTriggerPanel } from '@/components/model-lab/TrainingTriggerPanel';
import { fetchTrainingStatus, startTrainingBatch } from '@/lib/api/registry';
import type { TrainingBatchSummary, TrainingRunAck, TrainingStatus } from '@/lib/api/registry';

jest.mock('@/lib/api/registry');

const mockStart = startTrainingBatch as jest.MockedFunction<typeof startTrainingBatch>;
const mockStatus = fetchTrainingStatus as jest.MockedFunction<typeof fetchTrainingStatus>;

const SUMMARY: TrainingBatchSummary = {
  model_type: 'xgboost',
  attempted_today: 5,
  trained_this_call: 3,
  failed_this_call: 0,
  quota_reached: false,
  activated_this_call: 2,
  error: null,
};

const STARTED_ACK: TrainingRunAck = { model_type: 'xgboost', status: 'started' };

describe('TrainingTriggerPanel', () => {
  afterEach(() => {
    jest.clearAllMocks();
    jest.useRealTimers();
  });

  it('🆕 P14: モデルタイプごとに平易な説明と既定設定を表示する', () => {
    render(<TrainingTriggerPanel />);

    expect(screen.getByText(/表形式データの学習が得意な高速AI/)).toBeInTheDocument();
    expect(screen.getByText('既定設定: 決定木100本・木の深さ5・学習率0.1')).toBeInTheDocument();
  });

  it('4モデルタイプの学習ボタンを表示する', () => {
    render(<TrainingTriggerPanel />);

    expect(screen.getByText('XGBoost')).toBeInTheDocument();
    expect(screen.getByText('RandomForest')).toBeInTheDocument();
    expect(screen.getByText('LSTM')).toBeInTheDocument();
    expect(screen.getByText('Transformer')).toBeInTheDocument();
  });

  it('学習実行ボタンでバックグラウンド起動し、完了時に結果サマリを表示する', async () => {
    mockStart.mockResolvedValue(STARTED_ACK);
    mockStatus.mockResolvedValue({
      model_type: 'xgboost',
      running: false,
      attempted_today: 5,
      last_result: SUMMARY,
    });
    const user = userEvent.setup();

    render(<TrainingTriggerPanel />);
    const buttons = screen.getAllByRole('button', { name: '今すぐ学習' });
    await user.click(buttons[0]);

    await waitFor(() => expect(mockStart).toHaveBeenCalledWith('xgboost'));
    expect(await screen.findByText(/今回学習 3/)).toBeInTheDocument();
    expect(screen.getByText(/champion化 2/)).toBeInTheDocument();
  });

  it('実行中は試行済み件数をポーリングして表示し、完了後に結果へ切り替わる', async () => {
    jest.useFakeTimers({ legacyFakeTimers: false });
    mockStart.mockResolvedValue(STARTED_ACK);
    let call = 0;
    mockStatus.mockImplementation(async (): Promise<TrainingStatus> => {
      call += 1;
      if (call === 1) return { model_type: 'xgboost', running: true, attempted_today: 12, last_result: null };
      return { model_type: 'xgboost', running: false, attempted_today: 40, last_result: SUMMARY };
    });
    const user = userEvent.setup({ advanceTimers: jest.advanceTimersByTime });

    render(<TrainingTriggerPanel />);
    await user.click(screen.getAllByRole('button', { name: '今すぐ学習' })[0]);

    expect(await screen.findByText('試行済み(本日計) 12銘柄')).toBeInTheDocument();

    await jest.advanceTimersByTimeAsync(3000);

    expect(await screen.findByText(/今回学習 3/)).toBeInTheDocument();
  });

  it('学習結果がエラーを含む場合はエラー表示にする', async () => {
    mockStart.mockResolvedValue(STARTED_ACK);
    mockStatus.mockResolvedValue({
      model_type: 'xgboost',
      running: false,
      attempted_today: 0,
      last_result: { ...SUMMARY, error: 'unexpected failure' },
    });
    const user = userEvent.setup();

    render(<TrainingTriggerPanel />);
    await user.click(screen.getAllByRole('button', { name: '今すぐ学習' })[0]);

    expect(await screen.findByText(/学習の実行に失敗しました: unexpected failure/)).toBeInTheDocument();
  });

  it('起動リクエスト自体が失敗した場合はエラーメッセージを表示する', async () => {
    mockStart.mockRejectedValue(new Error('boom'));
    const user = userEvent.setup();

    render(<TrainingTriggerPanel />);
    await user.click(screen.getAllByRole('button', { name: '今すぐ学習' })[0]);

    expect(await screen.findByText('学習の起動に失敗しました')).toBeInTheDocument();
  });

  it('他のモデルタイプは実行中でも操作できる（🔧 P13h、独立実行）', async () => {
    mockStart.mockResolvedValue(STARTED_ACK);
    mockStatus.mockReturnValue(new Promise(() => undefined)); // 完了させない＝実行中のまま
    const user = userEvent.setup();

    render(<TrainingTriggerPanel />);
    const buttons = screen.getAllByRole('button', { name: '今すぐ学習' });
    await user.click(buttons[0]);

    await waitFor(() => expect(buttons[0]).toBeDisabled());
    expect(buttons[1]).not.toBeDisabled();
  });

  it('アクセシビリティ違反がない', async () => {
    const { container } = render(<TrainingTriggerPanel />);
    expect(await axe(container)).toHaveNoViolations();
  });
});
