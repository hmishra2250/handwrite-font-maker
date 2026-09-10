import { beforeEach, describe, expect, it, vi } from 'vitest';
const getUser = vi.fn();
vi.mock('@supabase/supabase-js', () => ({ createClient: () => ({ auth: { getUser, refreshSession: vi.fn() } }) }));
const origin = 'https://fonts.test';
function setup() {
  vi.stubEnv('DEPLOYMENT_MODE', 'invite_beta'); vi.stubEnv('SITE_URL', origin);
  vi.stubEnv('SUPABASE_URL', 'https://project.supabase.co'); vi.stubEnv('SUPABASE_ANON_KEY', 'anon');
  vi.stubEnv('INTERNAL_API_KEY', 's'.repeat(40)); vi.stubEnv('WORKER_API_BASE_URL', 'http://api:8000');
  getUser.mockResolvedValue({ data: { user: { id: 'owner', app_metadata: { handwrite_beta: true } } }, error: null });
}
function request(method: string, body?: unknown, auth = true) {
  return new Request(`${origin}/api/projects`, { method, headers: { origin, ...(auth ? { cookie: '__Host-hfm-access=access' } : {}), 'content-type': 'application/json' }, body: body === undefined ? undefined : JSON.stringify(body) });
}
describe('workspace proxy', () => {
  beforeEach(() => { vi.resetModules(); vi.restoreAllMocks(); vi.unstubAllEnvs(); setup(); });
  it('rejects missing authentication and wrong origin before forwarding', async () => {
    const fetcher = vi.spyOn(globalThis, 'fetch');
    const { POST } = await import('../api/projects/route');
    expect((await POST(request('POST', {}, false))).status).toBe(401);
    expect((await POST(new Request(`${origin}/api/projects`, { method: 'POST', headers: { origin: 'https://evil.test' }, body: '{}' }))).status).toBe(403);
    expect(fetcher).not.toHaveBeenCalled();
  });
  it('forwards verified identity, preserves409 and redacts backend details', async () => {
    const fetcher = vi.spyOn(globalThis, 'fetch').mockResolvedValue(Response.json({ error: { message: 'database password secret', code: 'CONFLICT' } }, { status: 409 }));
    const { PUT } = await import('../api/projects/[projectId]/route');
    const result = await PUT(request('PUT', { revision: 1 }), { params: Promise.resolve({ projectId: 'project_a' }) });
    expect(result.status).toBe(409); expect(result.headers.get('cache-control')).toBe('no-store');
    expect(await result.text()).not.toContain('secret');
    expect(fetcher).toHaveBeenCalledWith(new URL('http://api:8000/projects/project_a'), expect.objectContaining({ method: 'PUT', headers: expect.objectContaining({ authorization: 'Bearer access', 'x-internal-api-key': 's'.repeat(40) }) }));
  });
  it('bounds feedback bytes and reports storage failures without claiming saved', async () => {
    const fetcher = vi.spyOn(globalThis, 'fetch').mockRejectedValue(new Error('secret'));
    const { POST } = await import('../api/feedback/route');
    expect((await POST(request('POST', { message: 'x'.repeat(9000) }))).status).toBe(400);
    expect(fetcher).not.toHaveBeenCalled();
    const result = await POST(request('POST', { consent: true, topic: 'other', message: 'A valid message' }));
    expect(result.status).toBe(503); expect(await result.text()).not.toContain('secret');
  });
});
