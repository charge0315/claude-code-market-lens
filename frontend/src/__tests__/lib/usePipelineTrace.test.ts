import { act, renderHook, waitFor } from '@testing-library/react';
import { usePipelineTrace } from '@/lib/pipeline/usePipelineTrace';
import { fetchReplay } from '@/lib/api/inference';
import { subscribeSse, type SseHandlers } from '@/lib/realtime/sse';
import type { TraceEvent } from '@/lib/pipeline/types';

jest.mock('@/lib/api/inference');
jest.mock('@/lib/realtime/sse');

const mockFetchReplay = fetchReplay as jest.MockedFunction<typeof fetchReplay>;
const mockSubscribeSse = subscribeSse as jest.MockedFunction<typeof subscribeSse>;

function event(overrides: Partial<TraceEvent>): TraceEvent {
  return {
    run_id: 'run-1',
    pick_id: null,
    symbol: '7203',
    horizon_type: 'mid_term',
    started_at: '2026-06-01T08:50:00+09:00',
    finished_at: null,
    status: 'running',
    stage: 'collect',
    stage_status: 'done',
    stage_seq: 1,
    payload: {},
    event_at: '2026-06-01T08:50:01+09:00',
    ...overrides,
  };
}

describe('usePipelineTrace', () => {
  afterEach(() => {
    jest.clearAllMocks();
  });

  it('runId が無ければ何もしない', () => {
    const { result } = renderHook(() => usePipelineTrace(null, 'live'));
    expect(result.current.events).toEqual([]);
    expect(result.current.isActive).toBe(false);
    expect(mockSubscribeSse).not.toHaveBeenCalled();
  });

  it('live モードは SSE を購読しメッセージを蓄積する', () => {
    let captured: SseHandlers | null = null;
    mockSubscribeSse.mockImplementation((_path, handlers) => {
      captured = handlers;
      return { close: jest.fn() };
    });

    const { result } = renderHook(() => usePipelineTrace('run-1', 'live'));

    expect(mockSubscribeSse).toHaveBeenCalledWith('/api/inference/run-1/stream', expect.any(Object));
    expect(result.current.isActive).toBe(true);

    act(() => {
      captured?.onMessage?.(event({ stage: 'collect' }), new MessageEvent('message'));
    });
    expect(result.current.events).toHaveLength(1);

    act(() => {
      captured?.onNamed?.done(null, new MessageEvent('done'));
    });
    expect(result.current.isActive).toBe(false);
  });

  it('live モードの接続エラーでエラーメッセージを設定する', () => {
    let captured: SseHandlers | null = null;
    mockSubscribeSse.mockImplementation((_path, handlers) => {
      captured = handlers;
      return { close: jest.fn() };
    });

    const { result } = renderHook(() => usePipelineTrace('run-1', 'live'));
    act(() => {
      captured?.onError?.(new Event('error'));
    });
    expect(result.current.error).toBe('ライブ配信への接続に失敗しました');
    expect(result.current.isActive).toBe(false);
  });

  it('unmount 時に SSE 購読を close する', () => {
    const close = jest.fn();
    mockSubscribeSse.mockReturnValue({ close });

    const { unmount } = renderHook(() => usePipelineTrace('run-1', 'live'));
    unmount();
    expect(close).toHaveBeenCalled();
  });

  it('replay モードは保存イベントを1件ずつ間隔を空けて反映する', async () => {
    jest.useFakeTimers();
    mockFetchReplay.mockResolvedValue([
      event({ stage: 'collect', stage_seq: 1 }),
      event({ stage: 'subscore', stage_seq: 2 }),
    ]);

    const { result } = renderHook(() => usePipelineTrace('run-1', 'replay'));

    expect(mockFetchReplay).toHaveBeenCalledWith('run-1');
    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
    });
    expect(result.current.events).toHaveLength(1);

    act(() => {
      jest.advanceTimersByTime(600);
    });
    expect(result.current.events).toHaveLength(2);

    act(() => {
      jest.advanceTimersByTime(600);
    });
    expect(result.current.isActive).toBe(false);

    jest.useRealTimers();
  });

  it('replay モードの取得失敗でエラーメッセージを設定する', async () => {
    mockFetchReplay.mockRejectedValue(new Error('boom'));
    const { result } = renderHook(() => usePipelineTrace('run-1', 'replay'));

    await waitFor(() => expect(result.current.error).toBe('リプレイの取得に失敗しました'));
    expect(result.current.isActive).toBe(false);
  });
});
