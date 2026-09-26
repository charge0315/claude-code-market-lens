import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { axe } from 'jest-axe';
import { LLMProviderPanel } from '@/components/settings/LLMProviderPanel';
import { fetchLLMProviderSettings, updateLLMProviderSetting } from '@/lib/api/settings';
import type { LLMProviderSettingsResponse } from '@/lib/api/settings';

jest.mock('@/lib/api/settings');

const mockFetch = fetchLLMProviderSettings as jest.MockedFunction<typeof fetchLLMProviderSettings>;
const mockUpdate = updateLLMProviderSetting as jest.MockedFunction<typeof updateLLMProviderSetting>;

const MODELS = { anthropic: 'claude-sonnet-5', openai: 'gpt-5.1', gemini: 'gemini-2.5-pro' };

const INITIAL: LLMProviderSettingsResponse = {
  restart_required: false,
  available_providers: [
    {
      value: 'anthropic',
      label: 'Anthropic（Claude）',
      configured: true,
      default_model: 'claude-sonnet-5',
      model_presets: ['claude-opus-5', 'claude-sonnet-5'],
    },
    {
      value: 'openai',
      label: 'OpenAI（ChatGPT）',
      configured: false,
      default_model: 'gpt-5.1',
      model_presets: ['gpt-5.1'],
    },
    {
      value: 'gemini',
      label: 'Gemini',
      configured: true,
      default_model: 'gemini-2.5-pro',
      model_presets: ['gemini-2.5-pro', 'gemini-2.5-flash'],
    },
  ],
  features: [
    {
      feature: 'stock_pick',
      label: 'AIピック判定',
      primary_provider: 'anthropic',
      shadow_providers: ['gemini'],
      models: { ...MODELS },
    },
    {
      feature: 'portfolio_signal',
      label: 'ポートフォリオ売買判定',
      primary_provider: 'anthropic',
      shadow_providers: ['gemini'],
      models: { ...MODELS },
    },
    {
      feature: 'eod_review',
      label: 'EODレビュー',
      primary_provider: 'anthropic',
      shadow_providers: [],
      models: { ...MODELS },
    },
    {
      feature: 'trend_analyzer',
      label: 'トレンド抽出',
      primary_provider: 'anthropic',
      shadow_providers: [],
      models: { ...MODELS },
    },
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

  it('公式プロバイダの現在の使用モデルを入力欄に表示する', async () => {
    mockFetch.mockResolvedValue(INITIAL);
    render(<LLMProviderPanel />);
    await screen.findByText('AIピック判定');

    const rows = screen.getAllByRole('listitem');
    const modelInput = within(rows[0]).getByLabelText('Anthropic（Claude） の使用モデル') as HTMLInputElement;
    expect(modelInput.value).toBe('claude-sonnet-5');
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

  it('公式プロバイダを切り替えるとモデル入力欄も切り替わる', async () => {
    const user = userEvent.setup();
    mockFetch.mockResolvedValue(INITIAL);

    render(<LLMProviderPanel />);
    await screen.findByText('AIピック判定');

    const rows = screen.getAllByRole('listitem');
    const select = within(rows[0]).getByLabelText('公式プロバイダ（判定を左右する）');
    await user.selectOptions(select, 'openai');

    expect(within(rows[0]).getByLabelText('OpenAI（ChatGPT） の使用モデル')).toBeInTheDocument();
  });

  it('モデル入力欄を編集すると保存ボタンが有効になり、変更内容が送信される', async () => {
    const user = userEvent.setup();
    mockFetch.mockResolvedValue(INITIAL);
    mockUpdate.mockResolvedValue(INITIAL);

    render(<LLMProviderPanel />);
    await screen.findByText('AIピック判定');

    const rows = screen.getAllByRole('listitem');
    const modelInput = within(rows[0]).getByLabelText('Anthropic（Claude） の使用モデル');
    await user.clear(modelInput);
    await user.type(modelInput, 'claude-opus-5');

    const saveButton = within(rows[0]).getByRole('button', { name: '保存' });
    expect(saveButton).toBeEnabled();
    await user.click(saveButton);

    await waitFor(() =>
      expect(mockUpdate).toHaveBeenCalledWith({
        feature: 'stock_pick',
        primary_provider: 'anthropic',
        shadow_providers: ['gemini'],
        models: { ...MODELS, anthropic: 'claude-opus-5' },
      }),
    );
  });

  it('変更を保存すると再起動が必要な旨を表示する', async () => {
    const user = userEvent.setup();
    mockFetch.mockResolvedValue(INITIAL);
    mockUpdate.mockResolvedValue({
      ...INITIAL,
      restart_required: true,
      features: [{ ...INITIAL.features[0], primary_provider: 'openai' }, ...INITIAL.features.slice(1)],
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
        models: MODELS,
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
        models: MODELS,
      }),
    );
  });

  it('チェックしたシャドウプロバイダのモデル入力欄が表示される', async () => {
    const user = userEvent.setup();
    mockFetch.mockResolvedValue(INITIAL);

    render(<LLMProviderPanel />);
    await screen.findByText('AIピック判定');

    const rows = screen.getAllByRole('listitem');
    const openaiCheckbox = within(rows[0]).getByRole('checkbox', { name: /OpenAI/ });
    await user.click(openaiCheckbox);

    expect(within(rows[0]).getByLabelText('OpenAI（ChatGPT） の使用モデル')).toBeInTheDocument();
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
