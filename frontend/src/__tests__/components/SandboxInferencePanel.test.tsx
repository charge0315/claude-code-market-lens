import { act, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { axe } from 'jest-axe';
import { SandboxInferencePanel } from '@/components/chart/SandboxInferencePanel';
import { ApiError } from '@/lib/api/client';
import { fetchSandboxShadow, triggerSandboxInference } from '@/lib/api/inference';
import { subscribeSse, type SseHandlers } from '@/lib/realtime/sse';
import type { ShadowPrediction } from '@/lib/api/picks';

jest.mock('@/lib/api/inference');
jest.mock('@/lib/realtime/sse');

const mockTrigger = triggerSandboxInference as jest.MockedFunction<typeof triggerSandboxInference>;
const mockFetchShadow = fetchSandboxShadow as jest.MockedFunction<typeof fetchSandboxShadow>;
const mockSubscribeSse = subscribeSse as jest.MockedFunction<typeof subscribeSse>;

function shadow(overrides?: Partial<ShadowPrediction>): ShadowPrediction {
  return {
    shadow_id: 'shadow-1',
    challenger_version: 'gemini:gemini-2.5-pro',
    direction: 'bullish',
    entry: 1000,
    stop: 950,
    target: 1100,
    confidence: 70,
    reasoning: 'Gemini 側の根拠',
    risk_factors: [],
    holding_period_days: 6,
    issued_at: '2026-06-01T08:50:00+09:00',
    ...overrides,
  };
}

describe('SandboxInferencePanel', () => {
  afterEach(() => {
    jest.clearAllMocks();
  });

  it('ホライズン選択・実行ボタン・注意書きを表示する', () => {
    render(<SandboxInferencePanel symbol="7203" />);

    expect(screen.getByRole('group', { name: 'ホライズン' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: '中長期' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: '短期' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'AI推論を実行' })).toBeInTheDocument();
    expect(screen.getByText(/LLM呼び出しが発生し課金対象です/)).toBeInTheDocument();
    expect(screen.getByText('「AI推論を実行」を押すと、4分析から検証ゲートまでの経緯がここに表示されます')).toBeInTheDocument();
  });

  it('実行ボタンを押すとトリガーAPIを呼びライブ接続する', async () => {
    mockTrigger.mockResolvedValue({ run_id: 'run-sandbox-1' });
    mockSubscribeSse.mockReturnValue({ close: jest.fn() });
    const user = userEvent.setup();

    render(<SandboxInferencePanel symbol="7203" />);
    await user.click(screen.getByRole('button', { name: 'AI推論を実行' }));

    await waitFor(() => expect(mockTrigger).toHaveBeenCalledWith('7203', 'mid_term'));
    await waitFor(() =>
      expect(mockSubscribeSse).toHaveBeenCalledWith('/api/inference/run-sandbox-1/stream', expect.any(Object)),
    );
  });

  it('短期を選んでから実行すると short_term で呼ぶ', async () => {
    mockTrigger.mockResolvedValue({ run_id: 'run-sandbox-2' });
    mockSubscribeSse.mockReturnValue({ close: jest.fn() });
    const user = userEvent.setup();

    render(<SandboxInferencePanel symbol="7203" />);
    await user.click(screen.getByRole('button', { name: '短期' }));
    await user.click(screen.getByRole('button', { name: 'AI推論を実行' }));

    await waitFor(() => expect(mockTrigger).toHaveBeenCalledWith('7203', 'short_term'));
  });

  it('コスト上限超過（429）は専用メッセージを表示する', async () => {
    mockTrigger.mockRejectedValue(new ApiError('本日のLLM利用コスト上限に達したため実行できません', 429));
    const user = userEvent.setup();

    render(<SandboxInferencePanel symbol="7203" />);
    await user.click(screen.getByRole('button', { name: 'AI推論を実行' }));

    expect(await screen.findByText('本日のLLM利用コスト上限に達したため実行できません')).toBeInTheDocument();
  });

  it('多重トリガー（409）は専用メッセージを表示する', async () => {
    mockTrigger.mockRejectedValue(new ApiError('この銘柄は既に推論を実行中です', 409));
    const user = userEvent.setup();

    render(<SandboxInferencePanel symbol="7203" />);
    await user.click(screen.getByRole('button', { name: 'AI推論を実行' }));

    expect(await screen.findByText('この銘柄は既に推論を実行中です')).toBeInTheDocument();
  });

  it('ライブトレースが完了すると他LLM判定を取得して表示する', async () => {
    mockTrigger.mockResolvedValue({ run_id: 'run-sandbox-3' });
    let captured: SseHandlers | null = null;
    mockSubscribeSse.mockImplementation((_path, handlers) => {
      captured = handlers;
      return { close: jest.fn() };
    });
    mockFetchShadow.mockResolvedValue([shadow()]);
    const user = userEvent.setup();

    render(<SandboxInferencePanel symbol="7203" />);
    await user.click(screen.getByRole('button', { name: 'AI推論を実行' }));
    await waitFor(() => expect(mockSubscribeSse).toHaveBeenCalled());

    act(() => {
      captured?.onMessage?.(
        {
          run_id: 'run-sandbox-3',
          pick_id: null,
          symbol: '7203',
          horizon_type: 'mid_term',
          started_at: '2026-06-01T08:50:00+09:00',
          finished_at: '2026-06-01T08:50:04+09:00',
          status: 'done',
          stage: 'verify',
          stage_status: 'done',
          stage_seq: 6,
          payload: {},
          event_at: '2026-06-01T08:50:04+09:00',
        },
        new MessageEvent('message'),
      );
      captured?.onNamed?.done?.({}, new MessageEvent('done'));
    });

    await waitFor(() => expect(mockFetchShadow).toHaveBeenCalledWith('run-sandbox-3'));
    expect(await screen.findByText('他 LLM による判定（参考、比較用）')).toBeInTheDocument();
    expect(screen.getByText('Gemini 側の根拠')).toBeInTheDocument();
  });

  it('銘柄が切り替わると実行結果をリセットする', async () => {
    mockTrigger.mockResolvedValue({ run_id: 'run-sandbox-4' });
    mockSubscribeSse.mockReturnValue({ close: jest.fn() });
    const user = userEvent.setup();

    const { rerender } = render(<SandboxInferencePanel symbol="7203" />);
    await user.click(screen.getByRole('button', { name: 'AI推論を実行' }));
    await waitFor(() => expect(mockSubscribeSse).toHaveBeenCalled());

    rerender(<SandboxInferencePanel symbol="9984" />);

    expect(
      screen.getByText('「AI推論を実行」を押すと、4分析から検証ゲートまでの経緯がここに表示されます'),
    ).toBeInTheDocument();
  });

  it('アクセシビリティ違反がない', async () => {
    mockTrigger.mockResolvedValue({ run_id: 'run-sandbox-5' });
    mockSubscribeSse.mockReturnValue({ close: jest.fn() });

    const { container } = render(<SandboxInferencePanel symbol="7203" />);

    expect(await axe(container)).toHaveNoViolations();
  });
});
