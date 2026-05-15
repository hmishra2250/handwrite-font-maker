import { describe, expect, it, vi, beforeEach } from 'vitest';

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
    const res = await callCreateJob({
      inputPhoto: { objectKey: 'jobs/test/input/photo.jpg', contentType: 'image/jpeg', sizeBytes: 1024 },
      font: { fontName: 'bad font!!', familyName: 'Bad', styleName: 'Regular' },
    });
    expect(res.status).toBe(400);
    const data = await res.json();
    expect(data.error.code).toBe('FONT_METADATA_INVALID');
  });

  it('returns 202 demo response for valid input', async () => {
    const res = await callCreateJob({
      inputPhoto: { objectKey: 'jobs/test/input/photo.jpg', contentType: 'image/jpeg', sizeBytes: 1024 },
      font: { fontName: 'TestFont-Regular', familyName: 'Test Font', styleName: 'Regular' },
      template: { version: 'v1' },
    });
    expect(res.status).toBe(202);
    const data = await res.json();
    expect(data.jobId).toBeTruthy();
    expect(data.status).toBe('queued');
    expect(data.artifacts).toEqual([]);
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

  it('returns demo success for non-fail jobIds', async () => {
    const res = await callGetJob('demo_job_template_v1');
    expect(res.status).toBe(200);
    const data = await res.json();
    expect(data.jobId).toBeTruthy();
    expect(data.status).toBe('succeeded');
    expect(data.artifacts.length).toBeGreaterThan(0);
  });

  it('returns demo marker failure for fail jobIds', async () => {
    const res = await callGetJob('job_fail_test');
    expect(res.status).toBe(200);
    const data = await res.json();
    expect(data.status).toBe('failed');
    expect(data.error.code).toBe('MARKER_NOT_FOUND');
  });
});
