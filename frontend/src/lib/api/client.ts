// バックエンド（/api プロキシ経由）への薄い fetch ラッパ。
// 共通エンベロープ { success, data, error, meta } を剥がして data を返す。

export interface ApiEnvelope<T> {
  success: boolean;
  data: T | null;
  error: string | null;
  meta?: { total: number; page: number; limit: number } | null;
}

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
  ) {
    super(message);
    this.name = 'ApiError';
  }
}

const BASE = '/api';

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    ...init,
    headers: { 'Content-Type': 'application/json', ...(init?.headers ?? {}) },
  });

  const text = await res.text();
  const body = text ? (JSON.parse(text) as unknown) : null;

  if (!res.ok) {
    const msg = isEnvelope(body) && body.error ? body.error : `HTTP ${res.status}`;
    throw new ApiError(msg, res.status);
  }

  // エンベロープ形式なら data を取り出す。素の JSON（liveness 等）はそのまま返す。
  if (isEnvelope<T>(body)) {
    if (!body.success || body.data === null) {
      throw new ApiError(body.error ?? 'unknown error', res.status);
    }
    return body.data;
  }
  return body as T;
}

function isEnvelope<T>(body: unknown): body is ApiEnvelope<T> {
  return typeof body === 'object' && body !== null && 'success' in body && 'data' in body;
}

export const api = {
  get: <T>(path: string): Promise<T> => request<T>(path),
  post: <T>(path: string, payload?: unknown): Promise<T> =>
    request<T>(path, { method: 'POST', body: payload === undefined ? undefined : JSON.stringify(payload) }),
  patch: <T>(path: string, payload?: unknown): Promise<T> =>
    request<T>(path, { method: 'PATCH', body: payload === undefined ? undefined : JSON.stringify(payload) }),
  del: <T>(path: string): Promise<T> => request<T>(path, { method: 'DELETE' }),
};
