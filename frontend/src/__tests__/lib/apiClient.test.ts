import { api, ApiError } from '@/lib/api/client';

describe('api client', () => {
  const originalFetch = global.fetch;
  afterEach(() => {
    global.fetch = originalFetch;
    jest.restoreAllMocks();
  });

  function mockFetch(status: number, body: unknown): void {
    global.fetch = jest.fn().mockResolvedValue({
      ok: status >= 200 && status < 300,
      status,
      text: async () => JSON.stringify(body),
    }) as unknown as typeof fetch;
  }

  it('エンベロープ形式なら data を取り出して返す', async () => {
    mockFetch(200, { success: true, data: { picks: 3 }, error: null });
    await expect(api.get<{ picks: number }>('/picks/mid-term')).resolves.toEqual({ picks: 3 });
  });

  it('素の JSON（liveness 等）はそのまま返す', async () => {
    mockFetch(200, { status: 'ok', version: '0.1.0' });
    await expect(api.get<{ status: string }>('/health')).resolves.toEqual({ status: 'ok', version: '0.1.0' });
  });

  it('success=true かつ data=null は「該当データなし」として null を返す（エラーにしない）', async () => {
    mockFetch(200, { success: true, data: null, error: null });
    await expect(api.get('/portfolio/eod-review')).resolves.toBeNull();
  });

  it('success=false なら error を持つ ApiError を投げる', async () => {
    mockFetch(200, { success: false, data: null, error: '候補プールが空です' });
    await expect(api.get('/picks/mid-term')).rejects.toThrow('候補プールが空です');
  });

  it('HTTP エラーは status 付き ApiError を投げる', async () => {
    mockFetch(503, { success: false, data: null, error: 'DB down' });
    await expect(api.get('/picks/mid-term')).rejects.toMatchObject({ name: 'ApiError', status: 503 } as Partial<ApiError>);
  });
});
