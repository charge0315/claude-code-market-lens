import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { axe } from 'jest-axe';
import { TrainingTargetPanel } from '@/components/settings/TrainingTargetPanel';
import {
  fetchTickerUniverse,
  fetchTrainingTargetSettings,
  fetchTrainingTargetTickers,
  updateTrainingTargetSettings,
} from '@/lib/api/registry';
import type { TrainingTargetSettings, TrainingTargetTicker } from '@/lib/api/registry';

jest.mock('@/lib/api/registry');

const mockFetchSettings = fetchTrainingTargetSettings as jest.MockedFunction<typeof fetchTrainingTargetSettings>;
const mockUpdateSettings = updateTrainingTargetSettings as jest.MockedFunction<typeof updateTrainingTargetSettings>;
const mockFetchTickers = fetchTrainingTargetTickers as jest.MockedFunction<typeof fetchTrainingTargetTickers>;
const mockFetchUniverse = fetchTickerUniverse as jest.MockedFunction<typeof fetchTickerUniverse>;

const DEFAULT_SETTINGS: TrainingTargetSettings = { target_mode: 'all', max_parallel_workers: 4 };
const CUSTOM_TICKERS: TrainingTargetTicker[] = [
  { code: '7203', name: 'トヨタ自動車', sector: '輸送用機器', added_at: '2026-09-01T00:00:00+09:00' },
];

describe('TrainingTargetPanel', () => {
  beforeEach(() => {
    mockFetchSettings.mockResolvedValue(DEFAULT_SETTINGS);
    mockFetchTickers.mockResolvedValue([]);
    mockFetchUniverse.mockResolvedValue([]);
  });

  afterEach(() => {
    jest.clearAllMocks();
  });

  it('現在の学習対象モードと並列数上限を表示する', async () => {
    render(<TrainingTargetPanel />);
    expect(await screen.findByRole('radio', { name: '全銘柄' })).toBeChecked();
    expect(screen.getByLabelText('並列学習プロセス数の上限（デフォルト4）')).toHaveValue(4);
  });

  it('未変更では保存ボタンが無効', async () => {
    render(<TrainingTargetPanel />);
    await screen.findByRole('radio', { name: '全銘柄' });
    expect(screen.getByRole('button', { name: '保存' })).toBeDisabled();
  });

  it('モードを変更すると保存でき、保存後は再起動不要の通知を表示する', async () => {
    const user = userEvent.setup();
    mockUpdateSettings.mockResolvedValue({ target_mode: 'portfolio', max_parallel_workers: 4 });

    render(<TrainingTargetPanel />);
    await user.click(await screen.findByRole('radio', { name: 'ポートフォリオにあるもの' }));

    const saveButton = screen.getByRole('button', { name: '保存' });
    expect(saveButton).toBeEnabled();
    await user.click(saveButton);

    await waitFor(() =>
      expect(mockUpdateSettings).toHaveBeenCalledWith({ target_mode: 'portfolio', max_parallel_workers: 4 }),
    );
    expect(await screen.findByText(/再起動不要/)).toBeInTheDocument();
  });

  it('カスタムリストを選ぶと編集ボタンと登録件数を表示する', async () => {
    const user = userEvent.setup();
    mockFetchTickers.mockResolvedValue(CUSTOM_TICKERS);

    render(<TrainingTargetPanel />);
    await user.click(await screen.findByRole('radio', { name: '学習対象銘柄リスト（カスタム）' }));

    expect(await screen.findByText('現在 1 銘柄が登録されています。')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'カスタムリストを編集' })).toBeInTheDocument();
  });

  it('カスタムリスト編集ボタンでポップアップを開く', async () => {
    const user = userEvent.setup();
    render(<TrainingTargetPanel />);
    await user.click(await screen.findByRole('radio', { name: '学習対象銘柄リスト（カスタム）' }));
    await user.click(await screen.findByRole('button', { name: 'カスタムリストを編集' }));

    expect(await screen.findByRole('dialog', { name: '学習対象銘柄リストの編集' })).toBeInTheDocument();
  });

  it('並列数の上限を超えた値は上限にクランプする', async () => {
    const user = userEvent.setup();
    render(<TrainingTargetPanel />);
    const input = await screen.findByLabelText('並列学習プロセス数の上限（デフォルト4）');
    await user.clear(input);
    await user.type(input, '999');

    expect(input).toHaveValue(16);
  });

  it('取得失敗でエラーメッセージを出す', async () => {
    mockFetchSettings.mockRejectedValue(new Error('boom'));
    render(<TrainingTargetPanel />);
    expect(await screen.findByText('学習対象設定の取得に失敗しました')).toBeInTheDocument();
  });

  it('アクセシビリティ違反がない', async () => {
    const { container } = render(<TrainingTargetPanel />);
    await screen.findByRole('radio', { name: '全銘柄' });
    expect(await axe(container)).toHaveNoViolations();
  });
});
