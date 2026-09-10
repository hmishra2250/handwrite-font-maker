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

  it('rejects invalid segmentation method, style, and threshold fields', async () => {
    let res = await callForeground({ inputPhoto, rectangle, method: 'threshold' });
    expect(res.status).toBe(400);
    expect((await res.json()).error.message).toContain('method');

    res = await callForeground({ inputPhoto, rectangle, style: 'color' });
    expect(res.status).toBe(400);
    expect((await res.json()).error.message).toContain('style');

    res = await callForeground({ inputPhoto, rectangle, style: 'ink', threshold: 255 });
    expect(res.status).toBe(400);
    expect((await res.json()).error.message).toContain('threshold');

    res = await callForeground({ inputPhoto, rectangle, points: Array.from({ length: 17 }, () => ({ x: 0.5, y: 0.5, label: 1 })) });
    expect(res.status).toBe(400);
    expect((await res.json()).error.message).toContain('points');
  });

  it('requires a positive prompt point for explicit model extraction', async () => {
    const res = await callForeground({ inputPhoto, rectangle, method: 'model', points: [{ x: 0.1, y: 0.1, label: 0 }] });
    expect(res.status).toBe(400);
    const data = await res.json();
    expect(data.error.message).toContain('Keep object');
  });

  it('rejects box-model requests with point prompts before calling the worker', async () => {
    vi.stubEnv('WORKER_API_BASE_URL', 'http://api:8000');
    const fetchMock = vi.spyOn(globalThis, 'fetch');
    const res = await callForeground({ inputPhoto, rectangle, method: 'box-model', points: [{ x: 0.5, y: 0.5, label: 1 }] });
    expect(res.status).toBe(400);
    const data = await res.json();
    expect(data.error.code).toBe('CAPTURE_CONFIG_INVALID');
    expect(data.error.message).toContain('rectangle prompt');
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it('does not fake object cutout in demo mode', async () => {
    const res = await callForeground({ inputPhoto, rectangle });
    expect(res.status).toBe(503);
    const data = await res.json();
    expect(data.error.message).toContain('requires a configured Python worker');
  });

  it('returns 503 for explicit model extraction when no worker is configured', async () => {
    const res = await callForeground({ inputPhoto, rectangle, method: 'model', points: [{ x: 0.5, y: 0.5, label: 1 }] });
    expect(res.status).toBe(503);
    const data = await res.json();
    expect(data.error.message).toContain('Model foreground extraction requires');
  });

  it('proxies request fields to Python worker and validates grabcut mask response', async () => {
    vi.stubEnv('WORKER_API_BASE_URL', 'http://api:8000');
    const payload = { maskDataUrl: 'data:image/png;base64,bWFzaw==', width: 24, height: 32, method: 'grabcut', modelId: null, warnings: ['model unavailable; used grabcut'] };
    const responsePayload = { maskDataUrl: payload.maskDataUrl, width: 24, height: 32, method: 'grabcut', warnings: payload.warnings };
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockResolvedValue(Response.json(payload));
    const points = [{ x: 0.5, y: 0.4, label: 1 }, { x: 0.2, y: 0.1, label: 0 }];
    const res = await callForeground({ inputPhoto, rectangle, method: 'auto', style: 'ink', threshold: 128, points });
    expect(res.status).toBe(200);
    expect(await res.json()).toEqual(responsePayload);
    expect(fetchMock).toHaveBeenCalledWith(new URL('/capture/foreground', 'http://api:8000'), expect.objectContaining({ method: 'POST' }));
    expect(JSON.parse(String(fetchMock.mock.calls[0]?.[1]?.body))).toEqual({ inputPhoto, rectangle, method: 'auto', style: 'ink', threshold: 128, points });
  });

  it('accepts a slimsam model mask with model metadata', async () => {
    vi.stubEnv('WORKER_API_BASE_URL', 'http://api:8000');
    const payload = { maskDataUrl: 'data:image/png;base64,bWFzaw==', width: 24, height: 32, method: 'slimsam', modelId: 'slimsam-test' };
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(Response.json(payload));
    const res = await callForeground({ inputPhoto, rectangle, method: 'model', style: 'silhouette', points: [{ x: 0.5, y: 0.5, label: 1 }] });
    expect(res.status).toBe(200);
    expect(await res.json()).toEqual(payload);
  });

  it('accepts an EfficientSAM box-model mask without point prompts', async () => {
    vi.stubEnv('WORKER_API_BASE_URL', 'http://api:8000');
    const payload = { maskDataUrl: 'data:image/png;base64,bWFzaw==', width: 24, height: 32, method: 'efficientsam', modelId: 'effsam-test' };
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockResolvedValue(Response.json(payload));
    const res = await callForeground({ inputPhoto, rectangle, method: 'box-model', style: 'silhouette' });
    expect(res.status).toBe(200);
    expect(await res.json()).toEqual(payload);
    expect(JSON.parse(String(fetchMock.mock.calls[0]?.[1]?.body))).toEqual({ inputPhoto, rectangle, method: 'box-model', style: 'silhouette' });
  });
});
