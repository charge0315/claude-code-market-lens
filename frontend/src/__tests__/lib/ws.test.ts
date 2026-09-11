import { subscribeWs } from '@/lib/realtime/ws';

// jsdom には実ネットワークに繋がる WebSocket が無いため、コンストラクタ呼び出しと
// onopen/onmessage/onclose の発火を差し替え可能なフェイクで代替する。

class FakeWebSocket {
  static instances: FakeWebSocket[] = [];
  onopen: (() => void) | null = null;
  onmessage: ((event: { data: string }) => void) | null = null;
  onclose: (() => void) | null = null;
  closed = false;

  constructor(public url: string) {
    FakeWebSocket.instances.push(this);
  }

  close(): void {
    this.closed = true;
  }
}

describe('subscribeWs', () => {
  const originalWebSocket = global.WebSocket;

  beforeEach(() => {
    FakeWebSocket.instances = [];
    (global as unknown as { WebSocket: unknown }).WebSocket = FakeWebSocket;
  });

  afterEach(() => {
    (global as unknown as { WebSocket: unknown }).WebSocket = originalWebSocket;
    jest.useRealTimers();
  });

  it('接続すると onStatus("open") を通知する', () => {
    const onStatus = jest.fn();
    subscribeWs('/ws/notifications', { onMessage: jest.fn(), onStatus });

    FakeWebSocket.instances[0].onopen?.();

    expect(onStatus).toHaveBeenCalledWith('open');
  });

  it('受信したメッセージを JSON パースして onMessage へ渡す', () => {
    const onMessage = jest.fn();
    subscribeWs('/ws/notifications', { onMessage });

    FakeWebSocket.instances[0].onmessage?.({ data: JSON.stringify({ foo: 'bar' }) });

    expect(onMessage).toHaveBeenCalledWith({ foo: 'bar' });
  });

  it('JSON パースに失敗した場合は生データをそのまま渡す', () => {
    const onMessage = jest.fn();
    subscribeWs('/ws/notifications', { onMessage });

    FakeWebSocket.instances[0].onmessage?.({ data: 'not-json' });

    expect(onMessage).toHaveBeenCalledWith('not-json');
  });

  it('切断されると onStatus("reconnecting") を通知し再接続する', () => {
    jest.useFakeTimers();
    const onStatus = jest.fn();
    subscribeWs('/ws/notifications', { onMessage: jest.fn(), onStatus });

    FakeWebSocket.instances[0].onclose?.();
    expect(onStatus).toHaveBeenCalledWith('reconnecting');

    jest.advanceTimersByTime(1_000);
    expect(FakeWebSocket.instances).toHaveLength(2);
  });

  it('close() を呼ぶと再接続せず onStatus("closed") を通知する', () => {
    jest.useFakeTimers();
    const onStatus = jest.fn();
    const subscription = subscribeWs('/ws/notifications', { onMessage: jest.fn(), onStatus });

    subscription.close();

    expect(onStatus).toHaveBeenCalledWith('closed');
    expect(FakeWebSocket.instances[0].closed).toBe(true);

    // close() 後に onclose が発火しても再接続しない。
    FakeWebSocket.instances[0].onclose?.();
    jest.advanceTimersByTime(30_000);
    expect(FakeWebSocket.instances).toHaveLength(1);
  });
});
