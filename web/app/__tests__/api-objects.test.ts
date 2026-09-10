import { beforeEach, describe, expect, it, vi } from 'vitest';
import { MAX_UPLOAD_BYTES } from '@/lib/contracts';

describe('/api/objects/[...key] local proxy', () => {
  beforeEach(() => {
    vi.resetModules();
    vi.unstubAllEnvs();
    vi.restoreAllMocks();
  });

  async function putObject(size: number) {
    vi.stubEnv('WORKER_API_BASE_URL', 'http://api:8000');
    const { PUT } = await import('../api/objects/[...key]/route');
    const request = new Request('http://localhost:3000/api/objects/jobs/job/input/glyph.png', {
      method: 'PUT',
      headers: { 'content-type': 'image/png', 'content-length': String(size) },
      body: new Blob([new Uint8Array(Math.min(size, 32))], { type: 'image/png' }),
    });
    return PUT(request, { params: Promise.resolve({ key: ['jobs', 'job', 'input', 'glyph.png'] }) });
  }

  it('rejects oversized upload proxy requests before contacting worker', async () => {
    const fetchMock = vi.spyOn(globalThis, 'fetch');
    const res = await putObject(MAX_UPLOAD_BYTES + 1);
    expect(res.status).toBe(413);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it('proxies bounded uploads to Docker-internal worker URL', async () => {
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response(null, { status: 200 }));
    const res = await putObject(12);
    expect(res.status).toBe(200);
    expect(fetchMock).toHaveBeenCalledWith(new URL('/objects/jobs/job/input/glyph.png', 'http://api:8000'), expect.objectContaining({ method: 'PUT' }));
  });

  it('rejects oversized upload proxy bodies even when content-length is missing', async () => {
    vi.stubEnv('WORKER_API_BASE_URL', 'http://api:8000');
    const fetchMock = vi.spyOn(globalThis, 'fetch');
    const { PUT } = await import('../api/objects/[...key]/route');
    const request = new Request('http://localhost:3000/api/objects/jobs/job/input/glyph.png', {
      method: 'PUT',
      headers: { 'content-type': 'image/png', 'content-length': '1' },
      body: new ReadableStream({
        start(controller) {
          controller.enqueue(new Uint8Array(MAX_UPLOAD_BYTES + 1));
          controller.close();
        },
      }),
      duplex: 'half',
    } as RequestInit);
    const res = await PUT(request, { params: Promise.resolve({ key: ['jobs', 'job', 'input', 'glyph.png'] }) });
    expect(res.status).toBe(413);
    expect(fetchMock).not.toHaveBeenCalled();
  });

});
