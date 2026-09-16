import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { axe } from 'jest-axe';
import { LLMProviderPanel } from '@/components/settings/LLMProviderPanel';
import { fetchLLMProviderSettings, updateLLMProviderSetting } from '@/lib/api/settings';
import type { LLMProviderSettingsResponse } from '@/lib/api/settings';

jest.mock('@/lib/api/settings');

const mockFetch = fetchLLMProviderSettings as jest.MockedFunction<typeof fetchLLMProviderSettings>;
const mockUpdate = updateLLMProviderSetting as jest.MockedFunction<typeof updateLLMProviderSetting>;

const INITIAL: LLMProviderSettingsResponse = {
  restart_required: false,
  available_providers: [
    { value: 'anthropic', label: 'Anthropic（Claude）', configured: true },
    { value: 'openai', label: 'OpenAI（ChatGPT）', configured: false },
    { value: 'gemini', label: 'Gemini', configured: true },
  ],
  features: [
    { feature: 'stock_pick', label: 'AIピック判定', primary_provider: 'anthropic', shadow_providers: ['gemini'] },
    {
      feature: 'portfolio_signal',
      label: 'ポートフォリオ売買判定',
      primary_provider: 'anthropic',
      shadow_providers: ['gemini'],
    },
    { feature: 'eod_review', label: 'EODレビュー', primary_provider: 'anthropic', shadow_providers: [] },
    { feature: 'trend_analyzer', label: 'トレンド抽出', primary_provider: 'anthropic', shadow_providers: [] },
  ],
};

describe('LLMProviderPanel', () => {
  afterEach(() => {
    jest.clearAllMocks();
  });

  it('機能ごとの現在の公式/シャドウ設定を表示する', async () => {
    mockFetch.mockResolvedValue(INITIAL);

    render(<LLMProviderPanel />);

    expect(await screen.findByText('AIピック判定')).toBeInTheDocument();
    expect(screen.getByText('ポートフォリオ売買判定')).toBeInTheDocument();
    expect(screen.getByText('EODレビュー')).toBeInTheDocument();
    expect(screen.getByText('トレンド抽出')).toBeInTheDocument();
  });

  it('未設定プロバイダを公式に選ぶと警告を出す', async () => {
    const user = userEvent.setup();
    mockFetch.mockResolvedValue(INITIAL);

    render(<LLMProviderPanel />);
    await screen.findByText('AIピック判定');

    const select = screen.getAllByLabelText('公式プロバイダ（判定を左右する）')[0];
    await user.selectOptions(select, 'openai');

    expect(await screen.findByText(/OpenAI（ChatGPT）\s*の API キーが未設定/)).toBeInTheDocument();
  });

  it('変更を保存すると再起動が必要な旨を表示する', async () => {
    const user = userEvent.setup();
    mockFetch.mockResolvedValue(INITIAL);
    mockUpdate.mockResolvedValue({
      ...INITIAL,
      restart_required: true,
      features: [
        { feature: 'stock_pick', label: 'AIピック判定', primary_provider: 'openai', shadow_providers: ['gemini'] },
        ...INITIAL.features.slice(1),
      ],
    });

    render(<LLMProviderPanel />);
    await screen.findByText('AIピック判定');

    const select = screen.getAllByLabelText('公式プロバイダ（判定を左右する）')[0];
    await user.selectOptions(select, 'openai');

    const rows = screen.getAllByRole('listitem');
    const saveButton = within(rows[0]).getByRole('button', { name: '保存' });
    await user.click(saveButton);

    await waitFor(() =>
      expect(mockUpdate).toHaveBeenCalledWith({
        feature: 'stock_pick',
        primary_provider: 'openai',
        shadow_providers: ['gemini'],
      }),
    );
    expect(await screen.findByText(/再起動が必要です/)).toBeInTheDocument();
  });

  it('未変更では保存ボタンが無効', async () => {
    mockFetch.mockResolvedValue(INITIAL);
    render(<LLMProviderPanel />);
    await screen.findByText('AIピック判定');

    const saveButtons = screen.getAllByRole('button', { name: '保存' });
    saveButtons.forEach((btn) => expect(btn).toBeDisabled());
  });

  it('シャドウプロバイダのチェックを切り替えられる', async () => {
    const user = userEvent.setup();
    mockFetch.mockResolvedValue(INITIAL);
    mockUpdate.mockResolvedValue(INITIAL);

    render(<LLMProviderPanel />);
    await screen.findByText('AIピック判定');

    const rows = screen.getAllByRole('listitem');
    const openaiCheckbox = within(rows[0]).getByRole('checkbox', { name: /OpenAI/ });
    await user.click(openaiCheckbox);
    const saveButton = within(rows[0]).getByRole('button', { name: '保存' });
    await user.click(saveButton);

    await waitFor(() =>
      expect(mockUpdate).toHaveBeenCalledWith({
        feature: 'stock_pick',
        primary_provider: 'anthropic',
        shadow_providers: ['gemini', 'openai'],
      }),
    );
  });

  it('取得失敗でエラーメッセージを出す', async () => {
    mockFetch.mockRejectedValue(new Error('boom'));
    render(<LLMProviderPanel />);
    expect(await screen.findByText('LLMプロバイダ設定の取得に失敗しました')).toBeInTheDocument();
  });

  it('アクセシビリティ違反がない', async () => {
    mockFetch.mockResolvedValue(INITIAL);
    const { container } = render(<LLMProviderPanel />);
    await screen.findByText('AIピック判定');
    expect(await axe(container)).toHaveNoViolations();
  });
});
