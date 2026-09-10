import { describe, expect, it, vi, beforeEach } from 'vitest';

const validInputPhoto = { objectKey: 'jobs/test/input/photo.jpg', contentType: 'image/jpeg', sizeBytes: 1024 };
const validFont = { fontName: 'TestFont-Regular', familyName: 'Test Font', styleName: 'Regular' };

describe('POST /api/jobs', () => {
  beforeEach(() => {
    vi.resetModules();
    vi.unstubAllEnvs();
  });

  async function callCreateJob(body: unknown) {
    const { POST } = await import('../api/jobs/route');
    const request = new Request('http://localhost:3000/api/jobs', {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify(body),
    });
    return POST(request);
  }

  it('rejects missing inputPhoto with 400', async () => {
    const res = await callCreateJob({});
    expect(res.status).toBe(400);
    const data = await res.json();
    expect(data.error.code).toBe('UPLOAD_OBJECT_MISSING');
  });

  it('rejects invalid font name with 400', async () => {
    const res = await callCreateJob({ inputPhoto: validInputPhoto, font: { ...validFont, fontName: 'bad font!!' } });
    expect(res.status).toBe(400);
    const data = await res.json();
    expect(data.error.code).toBe('FONT_METADATA_INVALID');
  });

  it('rejects invalid capture configs before proxying', async () => {
    const res = await callCreateJob({
      inputPhoto: validInputPhoto,
      font: validFont,
      template: { version: 'v1' },
      capture: { mode: 'legacy' },
    });
    expect(res.status).toBe(400);
    const data = await res.json();
    expect(data.error.code).toBe('CAPTURE_CONFIG_INVALID');
  });

  it('returns 202 honest demo queued response without artifacts for valid input', async () => {
    const res = await callCreateJob({ inputPhoto: validInputPhoto, font: validFont, template: { version: 'v1' } });
    expect(res.status).toBe(202);
    const data = await res.json();
    expect(data.jobId).toBeTruthy();
    expect(data.status).toBe('queued');
    expect(data.artifacts).toEqual([]);
    expect(data.progressLabel).toContain('Demo mode');
  });

  it('proxies valid guided capture to the worker in local mode', async () => {
    vi.stubEnv('WORKER_API_BASE_URL', 'http://api:8000');
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockResolvedValue(Response.json({ jobId: 'job_local', status: 'queued', stage: 'queued', warnings: [], artifacts: [], retentionExpiresAt: new Date().toISOString() }, { status: 202 }));
    const res = await callCreateJob({
      inputPhoto: { objectKey: 'jobs/test/input/glyph-a.png', contentType: 'image/png', sizeBytes: 100 },
      font: validFont,
      template: { version: 'v1' },
      capture: { mode: 'guided', format: 'mask-v1', glyphs: [{ char: 'A', inputPhoto: { objectKey: 'jobs/test/input/glyph-a.png', contentType: 'image/png', sizeBytes: 100 }, baseline: 0.8 }] },
    });
    expect(res.status).toBe(202);
    expect(fetchMock).toHaveBeenCalledWith(new URL('/jobs', 'http://api:8000'), expect.objectContaining({ method: 'POST' }));
  });
});

describe('GET /api/jobs/[jobId]', () => {
  beforeEach(() => {
    vi.resetModules();
    vi.unstubAllEnvs();
  });

  async function callGetJob(jobId: string) {
    const { GET } = await import('../api/jobs/[jobId]/route');
    const request = new Request(`http://localhost:3000/api/jobs/${jobId}`);
    return GET(request, { params: Promise.resolve({ jobId }) });
  }

  it('returns honest demo backend-unavailable failure for non-fail jobIds', async () => {
    const res = await callGetJob('demo_job_template_v1');
    expect(res.status).toBe(200);
    const data = await res.json();
    expect(data.jobId).toBeTruthy();
    expect(data.status).toBe('failed');
    expect(data.artifacts).toEqual([]);
    expect(data.error.message).toContain('does not publish fake font files');
  });

  it('returns demo marker failure for fail jobIds', async () => {
    const res = await callGetJob('job_fail_test');
    expect(res.status).toBe(200);
    const data = await res.json();
    expect(data.status).toBe('failed');
    expect(data.error.code).toBe('MARKER_NOT_FOUND');
  });
});
