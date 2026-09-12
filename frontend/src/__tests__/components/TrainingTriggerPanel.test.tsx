import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { axe } from 'jest-axe';
import { TrainingTriggerPanel } from '@/components/model-lab/TrainingTriggerPanel';
import { runTrainingBatch } from '@/lib/api/registry';
import type { TrainingBatchSummary } from '@/lib/api/registry';

jest.mock('@/lib/api/registry');

const mockRunTrainingBatch = runTrainingBatch as jest.MockedFunction<typeof runTrainingBatch>;

const SUMMARY: TrainingBatchSummary = {
  model_type: 'xgboost',
  attempted_today: 5,
  trained_this_call: 3,
  failed_this_call: 0,
  quota_reached: false,
  activated_this_call: 2,
};

describe('TrainingTriggerPanel', () => {
  afterEach(() => {
    jest.clearAllMocks();
  });

  it('4モデルタイプの学習ボタンを表示する', () => {
    render(<TrainingTriggerPanel />);

    expect(screen.getByText('XGBoost')).toBeInTheDocument();
    expect(screen.getByText('RandomForest')).toBeInTheDocument();
    expect(screen.getByText('LSTM')).toBeInTheDocument();
    expect(screen.getByText('Transformer')).toBeInTheDocument();
  });

  it('学習実行ボタンで対応するモデルタイプを呼び出し、結果サマリを表示する', async () => {
    mockRunTrainingBatch.mockResolvedValue(SUMMARY);
    const user = userEvent.setup();

    render(<TrainingTriggerPanel />);
    const buttons = screen.getAllByRole('button', { name: '今すぐ学習' });
    await user.click(buttons[0]);

    await waitFor(() => expect(mockRunTrainingBatch).toHaveBeenCalledWith('xgboost'));
    expect(await screen.findByText(/今回学習 3/)).toBeInTheDocument();
    expect(screen.getByText(/champion化 2/)).toBeInTheDocument();
  });

  it('失敗時はエラーメッセージを表示する', async () => {
    mockRunTrainingBatch.mockRejectedValue(new Error('boom'));
    const user = userEvent.setup();

    render(<TrainingTriggerPanel />);
    await user.click(screen.getAllByRole('button', { name: '今すぐ学習' })[0]);

    expect(await screen.findByText('学習の実行に失敗しました')).toBeInTheDocument();
  });

  it('実行中は他のボタンも無効化される', async () => {
    let resolveFn: (value: TrainingBatchSummary) => void = () => undefined;
    mockRunTrainingBatch.mockReturnValue(
      new Promise((resolve) => {
        resolveFn = resolve;
      }),
    );
    const user = userEvent.setup();

    render(<TrainingTriggerPanel />);
    const buttons = screen.getAllByRole('button', { name: '今すぐ学習' });
    await user.click(buttons[0]);

    expect(buttons[1]).toBeDisabled();
    resolveFn(SUMMARY);
    await waitFor(() => expect(buttons[1]).not.toBeDisabled());
  });

  it('アクセシビリティ違反がない', async () => {
    const { container } = render(<TrainingTriggerPanel />);
    expect(await axe(container)).toHaveNoViolations();
  });
});
