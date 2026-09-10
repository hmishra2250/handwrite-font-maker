import { beforeEach, describe, expect, it, vi } from 'vitest';

const inputPhoto = { objectKey: 'jobs/test/input/original.jpg', contentType: 'image/jpeg', sizeBytes: 1024 };

describe('POST /api/capture/page', () => {
  beforeEach(() => {
    vi.resetModules();
    vi.unstubAllEnvs();
    vi.restoreAllMocks();
  });

  async function callCapture(body: unknown) {
    const { POST } = await import('../api/capture/page/route');
    return POST(new Request('http://localhost:3000/api/capture/page', {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify(body),
    }));
  }

  it('rejects missing input photo', async () => {
    const res = await callCapture({});
    expect(res.status).toBe(400);
    const data = await res.json();
    expect(data.error.code).toBe('UPLOAD_OBJECT_MISSING');
  });

  it('does not fake corner detection in demo mode', async () => {
    const res = await callCapture({ inputPhoto });
    expect(res.status).toBe(503);
    const data = await res.json();
    expect(data.error.message).toContain('requires a configured Python worker');
  });

  it('proxies to Python worker and validates normalized corners', async () => {
    vi.stubEnv('WORKER_API_BASE_URL', 'http://api:8000');
    const corners = [[0.1, 0.1], [0.9, 0.1], [0.9, 0.9], [0.1, 0.9]];
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockResolvedValue(Response.json({ corners }));
    const res = await callCapture({ inputPhoto });
    expect(res.status).toBe(200);
    expect(await res.json()).toEqual({ corners });
    expect(fetchMock).toHaveBeenCalledWith(new URL('/capture/page', 'http://api:8000'), expect.objectContaining({ method: 'POST' }));
  });

  it('rejects invalid worker corner output', async () => {
    vi.stubEnv('WORKER_API_BASE_URL', 'http://api:8000');
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(Response.json({ corners: [[-1, 0], [1, 0]] }));
    const res = await callCapture({ inputPhoto });
    expect(res.status).toBe(502);
    const data = await res.json();
    expect(data.error.code).toBe('CAPTURE_CONFIG_INVALID');
  });
});
