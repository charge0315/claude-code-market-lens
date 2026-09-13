import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { axe } from 'jest-axe';
import { ApiKeysPanel } from '@/components/settings/ApiKeysPanel';
import { fetchApiKeyStatus, updateApiKeys } from '@/lib/api/settings';
import type { ApiKeysResponse } from '@/lib/api/settings';

jest.mock('@/lib/api/settings');

const mockFetchStatus = fetchApiKeyStatus as jest.MockedFunction<typeof fetchApiKeyStatus>;
const mockUpdate = updateApiKeys as jest.MockedFunction<typeof updateApiKeys>;

const INITIAL: ApiKeysResponse = {
  restart_required: false,
  keys: [
    { key: 'anthropic_api_key', label: 'Anthropic API キー', configured: true, masked_value: '••••1234' },
    { key: 'gemini_api_key', label: 'Gemini API キー', configured: false, masked_value: null },
    { key: 'jquants_api_key', label: 'J-Quants API キー', configured: true, masked_value: '••••ab12' },
  ],
};

describe('ApiKeysPanel', () => {
  afterEach(() => {
    jest.clearAllMocks();
  });

  it('設定状況をマスク表示する', async () => {
    mockFetchStatus.mockResolvedValue(INITIAL);

    render(<ApiKeysPanel />);

    expect(await screen.findByText(/設定済み（••••1234）/)).toBeInTheDocument();
    expect(screen.getByText('未設定')).toBeInTheDocument();
  });

  it('新しい値を入力して保存すると再起動が必要な旨を表示する', async () => {
    const user = userEvent.setup();
    mockFetchStatus.mockResolvedValue(INITIAL);
    mockUpdate.mockResolvedValue({
      restart_required: true,
      keys: [
        { key: 'anthropic_api_key', label: 'Anthropic API キー', configured: true, masked_value: '••••wxyz' },
        { key: 'gemini_api_key', label: 'Gemini API キー', configured: false, masked_value: null },
        { key: 'jquants_api_key', label: 'J-Quants API キー', configured: true, masked_value: '••••ab12' },
      ],
    });

    render(<ApiKeysPanel />);
    await screen.findByText(/設定済み（••••1234）/);

    const inputs = screen.getAllByPlaceholderText('新しい値を入力すると置き換わります');
    await user.type(inputs[0], 'sk-ant-new-secret-wxyz');
    const saveButtons = screen.getAllByRole('button', { name: '保存' });
    await user.click(saveButtons[0]);

    await waitFor(() => expect(mockUpdate).toHaveBeenCalledWith({ anthropic_api_key: 'sk-ant-new-secret-wxyz' }));
    expect(await screen.findByText(/再起動が必要です/)).toBeInTheDocument();
    expect(await screen.findByText(/設定済み（••••wxyz）/)).toBeInTheDocument();
  });

  it('未入力では保存ボタンが無効', async () => {
    mockFetchStatus.mockResolvedValue(INITIAL);
    render(<ApiKeysPanel />);
    await screen.findByText(/設定済み（••••1234）/);

    const saveButtons = screen.getAllByRole('button', { name: '保存' });
    saveButtons.forEach((btn) => expect(btn).toBeDisabled());
  });

  it('取得失敗でエラーメッセージを出す', async () => {
    mockFetchStatus.mockRejectedValue(new Error('boom'));
    render(<ApiKeysPanel />);
    expect(await screen.findByText('設定状況の取得に失敗しました')).toBeInTheDocument();
  });

  it('アクセシビリティ違反がない', async () => {
    mockFetchStatus.mockResolvedValue(INITIAL);
    const { container } = render(<ApiKeysPanel />);
    await screen.findByText(/設定済み（••••1234）/);
    expect(await axe(container)).toHaveNoViolations();
  });
});
