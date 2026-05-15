import { describe, expect, it, vi, beforeEach } from 'vitest';

describe('POST /api/uploads', () => {
  beforeEach(() => {
    vi.resetModules();
    vi.unstubAllEnvs();
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
});
