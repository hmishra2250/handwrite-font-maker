import { beforeEach, describe, expect, it, vi } from 'vitest';

const inputPhoto = { objectKey: 'jobs/test/input/object.jpg', contentType: 'image/jpeg', sizeBytes: 1024 };
const rectangle = [0.1, 0.1, 0.9, 0.9];

describe('POST /api/capture/foreground', () => {
  beforeEach(() => {
    vi.resetModules();
    vi.unstubAllEnvs();
    vi.restoreAllMocks();
  });

  async function callForeground(body: unknown) {
    const { POST } = await import('../api/capture/foreground/route');
    return POST(new Request('http://localhost:3000/api/capture/foreground', {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify(body),
    }));
  }

  it('rejects missing input photo', async () => {
    const res = await callForeground({ rectangle });
    expect(res.status).toBe(400);
    const data = await res.json();
    expect(data.error.code).toBe('UPLOAD_OBJECT_MISSING');
  });

  it('rejects invalid normalized rectangle', async () => {
    const res = await callForeground({ inputPhoto, rectangle: [0.9, 0.1, 0.1, 0.9] });
    expect(res.status).toBe(400);
    const data = await res.json();
    expect(data.error.code).toBe('CAPTURE_CONFIG_INVALID');
  });

  it('does not fake object cutout in demo mode', async () => {
    const res = await callForeground({ inputPhoto, rectangle });
    expect(res.status).toBe(503);
    const data = await res.json();
    expect(data.error.message).toContain('requires a configured Python worker');
  });

  it('proxies to Python worker and validates grabcut mask response', async () => {
    vi.stubEnv('WORKER_API_BASE_URL', 'http://api:8000');
    const payload = { maskDataUrl: 'data:image/png;base64,bWFzaw==', width: 24, height: 32, method: 'grabcut' };
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockResolvedValue(Response.json(payload));
    const res = await callForeground({ inputPhoto, rectangle });
    expect(res.status).toBe(200);
    expect(await res.json()).toEqual(payload);
    expect(fetchMock).toHaveBeenCalledWith(new URL('/capture/foreground', 'http://api:8000'), expect.objectContaining({ method: 'POST' }));
  });
});
