import { describe, expect, it, vi, beforeEach } from 'vitest';

describe('POST /api/uploads', () => {
  beforeEach(() => {
    vi.resetModules();
    vi.unstubAllEnvs();
    vi.restoreAllMocks();
  });

  async function callUpload(body: unknown) {
    const { POST } = await import('../api/uploads/route');
    const request = new Request('http://localhost:3000/api/uploads', {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify(body),
    });
    return POST(request);
  }

  it('rejects missing fields with 400', async () => {
    const res = await callUpload({});
    expect(res.status).toBe(400);
    const data = await res.json();
    expect(data.error.code).toBe('UPLOAD_OBJECT_MISSING');
  });

  it('rejects unsupported content types with 415', async () => {
    const res = await callUpload({ filename: 'doc.pdf', contentType: 'application/pdf', sizeBytes: 1024 });
    expect(res.status).toBe(415);
    const data = await res.json();
    expect(data.error.code).toBe('UNSUPPORTED_IMAGE_TYPE');
  });

  it('rejects oversized uploads with 413', async () => {
    const res = await callUpload({ filename: 'big.jpg', contentType: 'image/jpeg', sizeBytes: 100 * 1024 * 1024 });
    expect(res.status).toBe(413);
    const data = await res.json();
    expect(data.error.code).toBe('UPLOAD_OBJECT_TOO_LARGE');
  });

  it('returns demo upload response when no backend is configured', async () => {
    const res = await callUpload({ filename: 'template.jpg', contentType: 'image/jpeg', sizeBytes: 2048 });
    expect(res.status).toBe(200);
    const data = await res.json();
    expect(data.mode).toBe('demo');
    expect(data.uploadUrl).toBeTruthy();
    expect(data.objectKey).toMatch(/^jobs\/job_/);
    expect(data.method).toBe('PUT');
  });

  it('returns same-origin object proxy URLs in local mode', async () => {
    vi.stubEnv('WORKER_API_BASE_URL', 'http://api:8000');
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(Response.json({ objectKey: 'jobs/job_local/input/original.jpg', expiresAt: '2026-09-10T00:00:00.000Z' }));
    const res = await callUpload({ filename: 'template.jpg', contentType: 'image/jpeg', sizeBytes: 2048 });
    expect(res.status).toBe(200);
    const data = await res.json();
    expect(data.mode).toBe('local');
    expect(data.uploadUrl).toBe('/api/objects/jobs/job_local/input/original.jpg');
  });

  it('passes through local worker upload errors instead of returning a usable slot', async () => {
    vi.stubEnv('WORKER_API_BASE_URL', 'http://api:8000');
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(Response.json({ error: { code: 'UPLOAD_OBJECT_TOO_LARGE', message: 'too large' } }, { status: 413 }));
    const res = await callUpload({ filename: 'template.jpg', contentType: 'image/jpeg', sizeBytes: 2048 });
    expect(res.status).toBe(413);
    const data = await res.json();
    expect(data.error.code).toBe('UPLOAD_OBJECT_TOO_LARGE');
  });

  it('returns 502 when local worker upload response omits the object key', async () => {
    vi.stubEnv('WORKER_API_BASE_URL', 'http://api:8000');
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(Response.json({}));
    const res = await callUpload({ filename: 'template.jpg', contentType: 'image/jpeg', sizeBytes: 2048 });
    expect(res.status).toBe(502);
    const data = await res.json();
    expect(data.error.code).toBe('UPLOAD_OBJECT_MISSING');
  });

  it('returns 500 for non-JSON local worker upload failures', async () => {
    vi.stubEnv('WORKER_API_BASE_URL', 'http://api:8000');
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response('not json', { status: 500, headers: { 'content-type': 'text/plain' } }));
    const res = await callUpload({ filename: 'template.jpg', contentType: 'image/jpeg', sizeBytes: 2048 });
    expect(res.status).toBe(500);
    const data = await res.json();
    expect(data.error.code).toBe('INTERNAL_ERROR');
  });

});
