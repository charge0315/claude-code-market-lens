// 通知 push（WebSocket）の購読ヘルパ。指数バックオフで自動再接続する。
// P7（ポートフォリオ & 通知）で使う。

export interface WsHandlers {
  onMessage: (data: unknown) => void;
  onStatus?: (status: 'open' | 'closed' | 'reconnecting') => void;
}

export interface WsSubscription {
  close: () => void;
}

const MAX_BACKOFF_MS = 30_000;
const BASE_BACKOFF_MS = 1_000;

function resolveWsUrl(path: string): string {
  // path はアプリ内相対（例: /ws/notifications）。同一オリジンの ws:// or wss:// に解決する。
  if (typeof window === 'undefined') return path;
  const proto = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
  return `${proto}//${window.location.host}${path}`;
}

export function subscribeWs(path: string, handlers: WsHandlers): WsSubscription {
  let socket: WebSocket | null = null;
  let attempt = 0;
  let closedByCaller = false;
  let reconnectTimer: ReturnType<typeof setTimeout> | undefined;

  const connect = (): void => {
    socket = new WebSocket(resolveWsUrl(path));

    socket.onopen = () => {
      attempt = 0;
      handlers.onStatus?.('open');
    };
    socket.onmessage = (event) => {
      try {
        handlers.onMessage(JSON.parse(event.data as string));
      } catch {
        handlers.onMessage(event.data);
      }
    };
    socket.onclose = () => {
      if (closedByCaller) return;
      handlers.onStatus?.('reconnecting');
      const delay = Math.min(BASE_BACKOFF_MS * 2 ** attempt, MAX_BACKOFF_MS);
      attempt += 1;
      reconnectTimer = setTimeout(connect, delay);
    };
  };

  connect();

  return {
    close: () => {
      closedByCaller = true;
      if (reconnectTimer) clearTimeout(reconnectTimer);
      socket?.close();
      handlers.onStatus?.('closed');
    },
  };
}
