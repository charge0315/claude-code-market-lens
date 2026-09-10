// 推論トレース配信（SSE）の購読ヘルパ。再接続はブラウザの EventSource に委ねつつ、
// 明示 close と型付き on(event, handler) を提供する。P6（AI 思考の可視化）で使う。

export interface SseHandlers {
  onMessage?: (data: unknown, event: MessageEvent) => void;
  onNamed?: Record<string, (data: unknown, event: MessageEvent) => void>;
  onError?: (event: Event) => void;
  onOpen?: (event: Event) => void;
}

export interface SseSubscription {
  close: () => void;
}

function parse(raw: string): unknown {
  try {
    return JSON.parse(raw);
  } catch {
    return raw;
  }
}

export function subscribeSse(path: string, handlers: SseHandlers): SseSubscription {
  // path はアプリ内相対（例: /api/inference/{run_id}/stream）。
  const source = new EventSource(path);

  if (handlers.onOpen) source.onopen = handlers.onOpen;
  if (handlers.onError) source.onerror = handlers.onError;
  if (handlers.onMessage) {
    source.onmessage = (event) => handlers.onMessage?.(parse(event.data), event);
  }
  for (const [name, fn] of Object.entries(handlers.onNamed ?? {})) {
    source.addEventListener(name, (event) => fn(parse((event as MessageEvent).data), event as MessageEvent));
  }

  return { close: () => source.close() };
}
