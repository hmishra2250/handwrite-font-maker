import { beforeEach, describe, expect, it, vi } from 'vitest';

const authMock = {
  getUser: vi.fn(),
  refreshSession: vi.fn(),
  signInWithPassword: vi.fn(),
  admin: { signOut: vi.fn() },
};

vi.mock('@supabase/supabase-js', () => ({
  createClient: vi.fn(() => ({ auth: authMock })),
}));

const inputPhoto = { objectKey: 'jobs/test/input/original.jpg', contentType: 'image/jpeg', sizeBytes: 1024 };
const validFont = { fontName: 'TestFont-Regular', familyName: 'Test Font', styleName: 'Regular' };
const cookie = '__Host-hfm-access=access-token; __Host-hfm-refresh=refresh-token';
const origin = 'https://beta.example.com';

function protectedEnv(overrides: Record<string, string | undefined> = {}) {
  vi.stubEnv('DEPLOYMENT_MODE', 'invite_beta');
  vi.stubEnv('SUPABASE_URL', 'https://project.supabase.co');
  vi.stubEnv('SUPABASE_ANON_KEY', 'anon-key');
  vi.stubEnv('INTERNAL_API_KEY', 'k'.repeat(32));
  vi.stubEnv('WORKER_API_BASE_URL', 'http://api:8000');
  vi.stubEnv('SITE_URL', origin);
  for (const [key, value] of Object.entries(overrides)) vi.stubEnv(key, value);
}

function mockVerifiedUser(token = 'access-token') {
  authMock.getUser.mockImplementation(async (jwt: string) => {
    if (jwt === token) return { data: { user: { id: 'user-1', email: 'invitee@example.com', app_metadata: { handwrite_beta: true } } }, error: null };
    return { data: { user: null }, error: new Error('invalid') };
  });
}

describe('invite beta auth boundary', () => {
  beforeEach(() => {
    vi.resetModules();
    vi.unstubAllEnvs();
    vi.restoreAllMocks();
    authMock.getUser.mockReset();
    authMock.refreshSession.mockReset();
    authMock.signInWithPassword.mockReset();
    authMock.admin.signOut.mockReset();
  });

  it('fails closed when protected deployment config is incomplete', async () => {
    protectedEnv({ INTERNAL_API_KEY: 'too-short' });
    const fetchMock = vi.spyOn(globalThis, 'fetch');
    const { POST } = await import('../api/uploads/route');
    const res = await POST(new Request('https://beta.example.com/api/uploads', {
      method: 'POST',
      headers: { origin, 'content-type': 'application/json' },
      body: JSON.stringify({ filename: 'a.png', contentType: 'image/png', sizeBytes: 10 }),
    }));
    expect(res.status).toBe(500);
    expect((await res.json()).error.message).toContain('not configured');
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it('rejects protected mutation routes without auth cookies before contacting the worker', async () => {
    protectedEnv();
    const fetchMock = vi.spyOn(globalThis, 'fetch');
    const { POST } = await import('../api/jobs/route');
    const res = await POST(new Request('https://beta.example.com/api/jobs', {
      method: 'POST',
      headers: { origin, 'content-type': 'application/json' },
      body: JSON.stringify({ inputPhoto, font: validFont, template: { version: 'v1' } }),
    }));
    expect(res.status).toBe(401);
    expect((await res.json()).error.code).toBe('AUTH_REQUIRED');
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it('rejects cross-origin mutations before token verification or worker fetch', async () => {
    protectedEnv();
    const fetchMock = vi.spyOn(globalThis, 'fetch');
    const { POST } = await import('../api/uploads/route');
    const res = await POST(new Request('https://beta.example.com/api/uploads', {
      method: 'POST',
      headers: { origin: 'https://evil.example.com', cookie, 'content-type': 'application/json' },
      body: JSON.stringify({ filename: 'a.png', contentType: 'image/png', sizeBytes: 10 }),
    }));
    expect(res.status).toBe(403);
    expect(authMock.getUser).not.toHaveBeenCalled();
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it('logs in with email/password, verifies the access token, sets HttpOnly cookies, and returns no tokens in JSON', async () => {
    protectedEnv();
    authMock.signInWithPassword.mockResolvedValue({
      data: { session: { access_token: 'new-access', refresh_token: 'new-refresh', expires_in: 3600 }, user: { id: 'user-1', email: 'invitee@example.com', app_metadata: { handwrite_beta: true } } },
      error: null,
    });
    authMock.getUser.mockResolvedValue({ data: { user: { id: 'user-1', email: 'invitee@example.com', app_metadata: { handwrite_beta: true } } }, error: null });
    const { POST } = await import('../api/auth/login/route');
    const res = await POST(new Request('https://beta.example.com/api/auth/login', {
      method: 'POST',
      headers: { origin, 'content-type': 'application/json' },
      body: JSON.stringify({ email: 'invitee@example.com', password: 'correct-password' }),
    }));
    expect(res.status).toBe(200);
    const bodyText = await res.text();
    expect(bodyText).toContain('invitee@example.com');
    expect(bodyText).not.toContain('new-access');
    expect(bodyText).not.toContain('new-refresh');
    const setCookie = res.headers.get('set-cookie') ?? '';
    expect(setCookie).toContain('__Host-hfm-access=');
    expect(setCookie).toContain('HttpOnly');
    expect(setCookie).toContain('Secure');
    expect(setCookie.toLowerCase()).toContain('samesite=lax');
    expect(authMock.getUser).toHaveBeenCalledWith('new-access');
    expect(res.headers.get('cache-control')).toBe('no-store');
  });

  it('refreshes an expired cookie server-side and forwards the refreshed bearer token', async () => {
    protectedEnv({ SITE_URL: 'http://localhost:3000' });
    authMock.getUser.mockImplementation(async (jwt: string) => {
      if (jwt === 'new-access') return { data: { user: { id: 'user-1', email: 'invitee@example.com', app_metadata: { handwrite_beta: true } } }, error: null };
      return { data: { user: null }, error: new Error('expired') };
    });
    authMock.refreshSession.mockResolvedValue({ data: { session: { access_token: 'new-access', refresh_token: 'new-refresh', expires_in: 3600 } }, error: null });
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockResolvedValue(Response.json({ jobId: 'job_1', status: 'queued', stage: 'queued', warnings: [], artifacts: [], retentionExpiresAt: new Date().toISOString() }, { status: 202 }));
    const { POST } = await import('../api/jobs/route');
    const res = await POST(new Request('http://localhost:3000/api/jobs', {
      method: 'POST',
      headers: { origin: 'http://localhost:3000', cookie: '__Host-hfm-access=old-access; __Host-hfm-refresh=refresh-token', 'content-type': 'application/json' },
      body: JSON.stringify({ inputPhoto, font: validFont, template: { version: 'v1' } }),
    }));
    expect(res.status).toBe(202);
    const headers = fetchMock.mock.calls[0]?.[1]?.headers as Record<string, string>;
    expect(headers.authorization).toBe('Bearer new-access');
    expect(headers['x-internal-api-key']).toBe('k'.repeat(32));
    expect(res.headers.get('set-cookie')).toContain('new-access');
  });

  it('uses authenticated Python upload slots in beta instead of direct Supabase storage URLs', async () => {
    protectedEnv();
    mockVerifiedUser();
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockResolvedValue(Response.json({ objectKey: 'jobs/job_beta/input/original.png', expiresAt: '2026-09-10T00:00:00.000Z' }));
    const { POST } = await import('../api/uploads/route');
    const res = await POST(new Request('https://beta.example.com/api/uploads', {
      method: 'POST',
      headers: { origin, cookie, 'content-type': 'application/json' },
      body: JSON.stringify({ filename: 'a.png', contentType: 'image/png', sizeBytes: 10 }),
    }));
    expect(res.status).toBe(200);
    const data = await res.json();
    expect(data.mode).toBe('local');
    expect(data.uploadUrl).toBe('/api/objects/jobs/job_beta/input/original.png');
    const headers = fetchMock.mock.calls[0]?.[1]?.headers as Record<string, string>;
    expect(headers.authorization).toBe('Bearer access-token');
    expect(headers['x-internal-api-key']).toBe('k'.repeat(32));
    expect(res.headers.get('cache-control')).toBe('no-store');
  });

  it('forwards auth credentials to protected capture requests', async () => {
    protectedEnv();
    mockVerifiedUser();
    const corners = [[0.1, 0.1], [0.9, 0.1], [0.9, 0.9], [0.1, 0.9]];
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockResolvedValue(Response.json({ corners }));
    const { POST } = await import('../api/capture/page/route');
    const res = await POST(new Request('https://beta.example.com/api/capture/page', {
      method: 'POST',
      headers: { origin, cookie, 'content-type': 'application/json' },
      body: JSON.stringify({ inputPhoto }),
    }));
    expect(res.status).toBe(200);
    const headers = fetchMock.mock.calls[0]?.[1]?.headers as Record<string, string>;
    expect(headers.authorization).toBe('Bearer access-token');
    expect(headers['x-internal-api-key']).toBe('k'.repeat(32));
  });

  it('proxies authenticated job deletion to the worker', async () => {
    protectedEnv();
    mockVerifiedUser();
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response(null, { status: 204 }));
    const { DELETE } = await import('../api/jobs/[jobId]/route');
    const res = await DELETE(new Request('https://beta.example.com/api/jobs/job_delete_me', {
      method: 'DELETE',
      headers: { origin, cookie },
    }), { params: Promise.resolve({ jobId: 'job_delete_me' }) });
    expect(res.status).toBe(200);
    expect(await res.json()).toEqual({ ok: true });
    expect(fetchMock).toHaveBeenCalledWith(new URL('/jobs/job_delete_me', 'http://api:8000'), expect.objectContaining({ method: 'DELETE' }));
    const headers = fetchMock.mock.calls[0]?.[1]?.headers as Record<string, string>;
    expect(headers.authorization).toBe('Bearer access-token');
    expect(headers['x-internal-api-key']).toBe('k'.repeat(32));
  });
  it('treats malformed cookie encoding as invalid without throwing', async () => {
    protectedEnv();
    const fetchMock = vi.spyOn(globalThis, 'fetch');
    const { POST } = await import('../api/jobs/route');
    const res = await POST(new Request('https://beta.example.com/api/jobs', {
      method: 'POST',
      headers: { origin, cookie: '__Host-hfm-access=%; __Host-hfm-refresh=%', 'content-type': 'application/json' },
      body: JSON.stringify({ inputPhoto, font: validFont, template: { version: 'v1' } }),
    }));
    expect(res.status).toBe(401);
    expect((await res.json()).error.code).toBe('AUTH_REQUIRED');
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it('returns a sanitized provider outage without clearing existing cookies', async () => {
    protectedEnv();
    authMock.getUser.mockRejectedValue(new Error('network down with provider internals'));
    const fetchMock = vi.spyOn(globalThis, 'fetch');
    const { POST } = await import('../api/jobs/route');
    const res = await POST(new Request('https://beta.example.com/api/jobs', {
      method: 'POST',
      headers: { origin, cookie, 'content-type': 'application/json' },
      body: JSON.stringify({ inputPhoto, font: validFont, template: { version: 'v1' } }),
    }));
    expect(res.status).toBe(503);
    const data = await res.json();
    expect(data.error.code).toBe('AUTH_PROVIDER_UNAVAILABLE');
    expect(data.error.message).not.toContain('provider internals');
    expect(res.headers.get('set-cookie') ?? '').not.toContain('Max-Age=0');
    expect(res.headers.get('cache-control')).toBe('no-store');
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it('fails closed for unknown deployment modes and unsafe protected URLs', async () => {
    protectedEnv({ DEPLOYMENT_MODE: 'staging' });
    const fetchMock = vi.spyOn(globalThis, 'fetch');
    const { POST } = await import('../api/uploads/route');
    const unknownMode = await POST(new Request('https://beta.example.com/api/uploads', {
      method: 'POST',
      headers: { origin, cookie, 'content-type': 'application/json' },
      body: JSON.stringify({ filename: 'a.png', contentType: 'image/png', sizeBytes: 10 }),
    }));
    expect(unknownMode.status).toBe(500);
    expect((await unknownMode.json()).error.message).toContain('not configured');
    expect(unknownMode.headers.get('cache-control')).toBe('no-store');
    expect(fetchMock).not.toHaveBeenCalled();

    vi.resetModules();
    protectedEnv({ WORKER_API_BASE_URL: 'http://user:pass@api:8000' });
    const unsafeWorker = await (await import('../api/uploads/route')).POST(new Request('https://beta.example.com/api/uploads', {
      method: 'POST',
      headers: { origin, cookie, 'content-type': 'application/json' },
      body: JSON.stringify({ filename: 'a.png', contentType: 'image/png', sizeBytes: 10 }),
    }));
    expect(unsafeWorker.status).toBe(500);
    expect((await unsafeWorker.json()).error.message).toContain('not configured');
    expect(fetchMock).not.toHaveBeenCalled();

    vi.resetModules();
    protectedEnv({ SUPABASE_URL: 'http://project.supabase.co' });
    const unsafeSupabase = await (await import('../api/uploads/route')).POST(new Request('https://beta.example.com/api/uploads', {
      method: 'POST',
      headers: { origin, cookie, 'content-type': 'application/json' },
      body: JSON.stringify({ filename: 'a.png', contentType: 'image/png', sizeBytes: 10 }),
    }));
    expect(unsafeSupabase.status).toBe(500);
    expect((await unsafeSupabase.json()).error.message).toContain('not configured');
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it('adds no-store to auth responses and protected refreshed responses', async () => {
    protectedEnv();
    authMock.signInWithPassword.mockResolvedValue({
      data: { session: { access_token: 'new-access', refresh_token: 'new-refresh', expires_in: 3600 }, user: { id: 'user-1', email: 'invitee@example.com', app_metadata: { handwrite_beta: true } } },
      error: null,
    });
    authMock.getUser.mockResolvedValue({ data: { user: { id: 'user-1', email: 'invitee@example.com', app_metadata: { handwrite_beta: true } } }, error: null });
    const login = await (await import('../api/auth/login/route')).POST(new Request('https://beta.example.com/api/auth/login', {
      method: 'POST',
      headers: { origin, 'content-type': 'application/json' },
      body: JSON.stringify({ email: 'invitee@example.com', password: 'correct-password' }),
    }));
    expect(login.status).toBe(200);
    expect(login.headers.get('cache-control')).toBe('no-store');

    const session = await (await import('../api/auth/session/route')).GET(new Request('https://beta.example.com/api/auth/session', { headers: { cookie } }));
    expect(session.status).toBe(200);
    expect(session.headers.get('cache-control')).toBe('no-store');

    const logout = await (await import('../api/auth/logout/route')).POST(new Request('https://beta.example.com/api/auth/logout', { method: 'POST', headers: { origin } }));
    expect(logout.status).toBe(200);
    expect(logout.headers.get('cache-control')).toBe('no-store');
  });

  it('fails closed when protected Supabase config exists without an explicit deployment mode', async () => {
    protectedEnv({ DEPLOYMENT_MODE: undefined });
    const fetchMock = vi.spyOn(globalThis, 'fetch');
    const { POST } = await import('../api/uploads/route');
    const res = await POST(new Request('https://beta.example.com/api/uploads', {
      method: 'POST',
      headers: { origin, cookie, 'content-type': 'application/json' },
      body: JSON.stringify({ filename: 'a.png', contentType: 'image/png', sizeBytes: 10 }),
    }));
    expect(res.status).toBe(500);
    expect((await res.json()).error.message).toContain('not configured');
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it('requires trusted invite app_metadata in invite_beta login and requests', async () => {
    protectedEnv();
    authMock.signInWithPassword.mockResolvedValue({
      data: { session: { access_token: 'new-access', refresh_token: 'new-refresh', expires_in: 3600 }, user: { id: 'user-2', email: 'not-invited@example.com' } },
      error: null,
    });
    authMock.getUser.mockResolvedValue({ data: { user: { id: 'user-2', email: 'not-invited@example.com', app_metadata: {} } }, error: null });
    const login = await (await import('../api/auth/login/route')).POST(new Request('https://beta.example.com/api/auth/login', {
      method: 'POST',
      headers: { origin, 'content-type': 'application/json' },
      body: JSON.stringify({ email: 'not-invited@example.com', password: 'correct-password' }),
    }));
    expect(login.status).toBe(403);
    const loginBody = await login.text();
    expect(loginBody).toContain('AUTH_INVITE_REQUIRED');
    expect(loginBody).not.toContain('not-invited@example.com');
    expect(login.headers.get('set-cookie') ?? '').not.toContain('__Host-hfm-access=');

    vi.resetModules();
    protectedEnv();
    authMock.getUser.mockResolvedValue({ data: { user: { id: 'user-2', email: 'not-invited@example.com', app_metadata: {} } }, error: null });
    const fetchMock = vi.spyOn(globalThis, 'fetch');
    const request = await (await import('../api/jobs/route')).POST(new Request('https://beta.example.com/api/jobs', {
      method: 'POST',
      headers: { origin, cookie, 'content-type': 'application/json' },
      body: JSON.stringify({ inputPhoto, font: validFont, template: { version: 'v1' } }),
    }));
    expect(request.status).toBe(403);
    expect((await request.json()).error.code).toBe('AUTH_INVITE_REQUIRED');
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it('rewrites protected worker local artifact URLs to authenticated same-origin object proxy paths', async () => {
    protectedEnv();
    mockVerifiedUser();
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(Response.json({
      jobId: 'job_done',
      status: 'succeeded',
      stage: 'complete',
      progressLabel: 'done',
      warnings: [],
      retentionExpiresAt: new Date().toISOString(),
      artifacts: [
        { kind: 'ttf', label: 'TrueType Font', objectKey: 'jobs/job_done/out/font.ttf', url: 'local://download/jobs/job_done/out/font.ttf?sig=unused', contentType: 'font/ttf', sizeBytes: 10 },
      ],
    }));
    const { GET } = await import('../api/jobs/[jobId]/route');
    const res = await GET(new Request('https://beta.example.com/api/jobs/job_done', { headers: { cookie } }), { params: Promise.resolve({ jobId: 'job_done' }) });
    expect(res.status).toBe(200);
    const data = await res.json();
    expect(data.artifacts[0].url).toBe('/api/objects/jobs/job_done/out/font.ttf');
    expect(res.headers.get('cache-control')).toBe('no-store');
  });


  it('revokes the Supabase local session with a valid access token before clearing cookies', async () => {
    protectedEnv();
    authMock.admin.signOut.mockResolvedValue({ data: null, error: null });
    const { POST } = await import('../api/auth/logout/route');
    const res = await POST(new Request('https://beta.example.com/api/auth/logout', { method: 'POST', headers: { origin, cookie } }));
    expect(res.status).toBe(200);
    expect(authMock.admin.signOut).toHaveBeenCalledWith('access-token', 'local');
    expect(authMock.refreshSession).not.toHaveBeenCalled();
    const setCookie = res.headers.get('set-cookie') ?? '';
    expect(setCookie).toContain('__Host-hfm-access=');
    expect(setCookie).toContain('Max-Age=0');
    expect(res.headers.get('cache-control')).toBe('no-store');
  });

  it('refreshes a valid refresh cookie to revoke logout when access is missing or expired', async () => {
    protectedEnv();
    authMock.refreshSession.mockResolvedValue({ data: { session: { access_token: 'logout-access', refresh_token: 'rotated-refresh', expires_in: 3600 } }, error: null });
    authMock.admin.signOut.mockResolvedValue({ data: null, error: null });
    const { POST } = await import('../api/auth/logout/route');
    const missingAccess = await POST(new Request('https://beta.example.com/api/auth/logout', { method: 'POST', headers: { origin, cookie: '__Host-hfm-refresh=refresh-token' } }));
    expect(missingAccess.status).toBe(200);
    expect(authMock.refreshSession).toHaveBeenCalledWith({ refresh_token: 'refresh-token' });
    expect(authMock.admin.signOut).toHaveBeenCalledWith('logout-access', 'local');
    expect(missingAccess.headers.get('set-cookie')).toContain('Max-Age=0');

    vi.resetModules();
    authMock.refreshSession.mockReset();
    authMock.admin.signOut.mockReset();
    protectedEnv();
    authMock.refreshSession.mockResolvedValue({ data: { session: { access_token: 'logout-access-2', refresh_token: 'rotated-refresh-2', expires_in: 3600 } }, error: null });
    authMock.admin.signOut.mockResolvedValueOnce({ data: null, error: { status: 401 } }).mockResolvedValueOnce({ data: null, error: null });
    const expiredAccess = await (await import('../api/auth/logout/route')).POST(new Request('https://beta.example.com/api/auth/logout', { method: 'POST', headers: { origin, cookie } }));
    expect(expiredAccess.status).toBe(200);
    expect(authMock.refreshSession).toHaveBeenCalledWith({ refresh_token: 'refresh-token' });
    expect(authMock.admin.signOut).toHaveBeenNthCalledWith(1, 'access-token', 'local');
    expect(authMock.admin.signOut).toHaveBeenNthCalledWith(2, 'logout-access-2', 'local');
    expect(expiredAccess.headers.get('set-cookie')).toContain('Max-Age=0');
  });

  it('clears cookies when logout has only an invalid refresh cookie', async () => {
    protectedEnv();
    authMock.refreshSession.mockResolvedValue({ data: { session: null }, error: { status: 400 } });
    const { POST } = await import('../api/auth/logout/route');
    const res = await POST(new Request('https://beta.example.com/api/auth/logout', { method: 'POST', headers: { origin, cookie: '__Host-hfm-refresh=invalid-refresh' } }));
    expect(res.status).toBe(200);
    expect(authMock.refreshSession).toHaveBeenCalledWith({ refresh_token: 'invalid-refresh' });
    expect(authMock.admin.signOut).not.toHaveBeenCalled();
    expect(res.headers.get('set-cookie')).toContain('Max-Age=0');
    expect(res.headers.get('cache-control')).toBe('no-store');
  });

  it('does not clear cookies when Supabase logout revocation is unavailable', async () => {
    protectedEnv();
    authMock.admin.signOut.mockRejectedValue(new Error('provider down with secret'));
    const { POST } = await import('../api/auth/logout/route');
    const res = await POST(new Request('https://beta.example.com/api/auth/logout', { method: 'POST', headers: { origin, cookie } }));
    expect(res.status).toBe(503);
    const body = await res.text();
    expect(body).toContain('AUTH_PROVIDER_UNAVAILABLE');
    expect(body).not.toContain('secret');
    expect(res.headers.get('set-cookie') ?? '').not.toContain('Max-Age=0');
    expect(res.headers.get('cache-control')).toBe('no-store');

    vi.resetModules();
    protectedEnv();
    authMock.refreshSession.mockRejectedValue(new Error('refresh provider down with secret'));
    const refreshOutage = await (await import('../api/auth/logout/route')).POST(new Request('https://beta.example.com/api/auth/logout', { method: 'POST', headers: { origin, cookie: '__Host-hfm-refresh=refresh-token' } }));
    expect(refreshOutage.status).toBe(503);
    expect(await refreshOutage.text()).toContain('AUTH_PROVIDER_UNAVAILABLE');
    expect(refreshOutage.headers.get('set-cookie') ?? '').not.toContain('Max-Age=0');
  });


  it('keeps rotated refresh cookies when post-refresh logout revocation is unavailable', async () => {
    protectedEnv();
    authMock.refreshSession.mockResolvedValue({
      data: { session: { access_token: 'rotated-access', refresh_token: 'rotated-refresh', expires_in: 1800 } },
      error: null,
    });
    authMock.admin.signOut
      .mockResolvedValueOnce({ data: null, error: { status: 401 } })
      .mockRejectedValueOnce(new Error('post-refresh signout provider down with secret'));
    const { POST } = await import('../api/auth/logout/route');
    const res = await POST(new Request('https://beta.example.com/api/auth/logout', { method: 'POST', headers: { origin, cookie } }));
    expect(res.status).toBe(503);
    const body = await res.text();
    expect(body).toContain('AUTH_PROVIDER_UNAVAILABLE');
    expect(body).not.toContain('secret');
    expect(authMock.refreshSession).toHaveBeenCalledWith({ refresh_token: 'refresh-token' });
    expect(authMock.admin.signOut).toHaveBeenNthCalledWith(1, 'access-token', 'local');
    expect(authMock.admin.signOut).toHaveBeenNthCalledWith(2, 'rotated-access', 'local');
    const setCookie = res.headers.get('set-cookie') ?? '';
    expect(setCookie).toContain('__Host-hfm-access=rotated-access');
    expect(setCookie).toContain('__Host-hfm-refresh=rotated-refresh');
    expect(setCookie).not.toContain('Max-Age=0');
    expect(res.headers.get('cache-control')).toBe('no-store');
  });

  it('treats malformed refresh success without a session as unavailable without clearing cookies', async () => {
    protectedEnv();
    authMock.refreshSession.mockResolvedValue({ data: { session: null }, error: null });
    const { POST } = await import('../api/auth/logout/route');
    const res = await POST(new Request('https://beta.example.com/api/auth/logout', { method: 'POST', headers: { origin, cookie: '__Host-hfm-refresh=refresh-token' } }));
    expect(res.status).toBe(503);
    expect(await res.text()).toContain('AUTH_PROVIDER_UNAVAILABLE');
    expect(authMock.refreshSession).toHaveBeenCalledWith({ refresh_token: 'refresh-token' });
    expect(authMock.admin.signOut).not.toHaveBeenCalled();
    expect(res.headers.get('set-cookie') ?? '').not.toContain('Max-Age=0');
    expect(res.headers.get('cache-control')).toBe('no-store');
  });

});
