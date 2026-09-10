import { beforeEach, describe, expect, it, vi } from 'vitest';
import { ACCESS_COOKIE, LOCAL_ALPHA_ACCESS_COOKIE } from '@/lib/server-auth';

const origin = 'https://alpha.example.com';
const localhostOrigin = 'http://localhost:3000';
const internalKey = 'a'.repeat(40);

function setup(overrides: Record<string, string | undefined> = {}) {
  vi.stubEnv('DEPLOYMENT_MODE', 'private_alpha');
  vi.stubEnv('SITE_URL', origin);
  vi.stubEnv('INTERNAL_API_KEY', internalKey);
  vi.stubEnv('WORKER_API_BASE_URL', 'http://api:8000');
  for (const [key, value] of Object.entries(overrides)) vi.stubEnv(key, value);
}

function req(path: string, init: RequestInit = {}, site = origin) {
  return new Request(`${site}${path}`, init);
}

describe('private alpha auth proxy', () => {
  beforeEach(() => {
    vi.resetModules();
    vi.restoreAllMocks();
    vi.unstubAllEnvs();
    setup();
  });

  it('logs in through the Python auth service and stores only an HttpOnly secure access cookie', async () => {
    const fetcher = vi.spyOn(globalThis, 'fetch').mockResolvedValue(Response.json({
      accessToken: 'alpha-access-token-12345',
      expiresIn: 86400,
      user: { id: 'user-alpha', email: 'alpha@example.com' },
    }));
    const { POST } = await import('../api/auth/login/route');
    const res = await POST(req('/api/auth/login', {
      method: 'POST',
      headers: { origin, 'content-type': 'application/json' },
      body: JSON.stringify({ email: 'alpha@example.com', password: 'valid-alpha-password' }),
    }));
    expect(res.status).toBe(200);
    const text = await res.text();
    expect(text).toContain('alpha@example.com');
    expect(text).not.toContain('alpha-access-token-12345');
    expect(fetcher).toHaveBeenCalledWith(new URL('/auth/login', 'http://api:8000'), expect.objectContaining({
      method: 'POST',
      headers: expect.objectContaining({ 'x-internal-api-key': internalKey }),
    }));
    const setCookie = res.headers.get('set-cookie') ?? '';
    expect(setCookie).toContain(`${ACCESS_COOKIE}=alpha-access-token-12345`);
    expect(setCookie).toContain('HttpOnly');
    expect(setCookie).toContain('Secure');
    expect(setCookie.toLowerCase()).toContain('samesite=lax');
    expect(setCookie).toContain('Max-Age=86400');
    expect(setCookie).toContain('__Host-hfm-refresh=');
    expect(res.headers.get('cache-control')).toBe('no-store');
  });

  it('uses a separate non-secure localhost cookie for HTTP local alpha e2e', async () => {
    setup({ SITE_URL: localhostOrigin });
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(Response.json({ accessToken: 'local-alpha-token-12345', expiresIn: 86400, user: { id: 'u', email: 'u@example.com' } }));
    const { POST } = await import('../api/auth/login/route');
    const res = await POST(req('/api/auth/login', {
      method: 'POST',
      headers: { origin: localhostOrigin, 'content-type': 'application/json' },
      body: JSON.stringify({ email: 'u@example.com', password: 'valid-alpha-password' }),
    }, localhostOrigin));
    expect(res.status).toBe(200);
    const setCookie = res.headers.get('set-cookie') ?? '';
    expect(setCookie).toContain(`${LOCAL_ALPHA_ACCESS_COOKIE}=local-alpha-token-12345`);
    expect(setCookie).not.toMatch(new RegExp(`${LOCAL_ALPHA_ACCESS_COOKIE}=[^;]+;[^,]*Secure`));
  });

  it('ignores localhost alpha cookies on HTTPS deployments without contacting the backend', async () => {
    const fetcher = vi.spyOn(globalThis, 'fetch');
    const { GET } = await import('../api/auth/session/route');
    const res = await GET(req('/api/auth/session', { headers: { cookie: `${LOCAL_ALPHA_ACCESS_COOKIE}=planted-parent-domain-token` } }));
    expect(res.status).toBe(401);
    expect((await res.json()).error.code).toBe('AUTH_REQUIRED');
    expect(fetcher).not.toHaveBeenCalled();
    expect(res.headers.get('set-cookie')).toContain('Max-Age=0');
  });

  it('checks sessions through Python with bearer plus internal key and clears expired cookies', async () => {
    const fetcher = vi.spyOn(globalThis, 'fetch').mockResolvedValueOnce(Response.json({ user: { id: 'user-alpha', email: 'alpha@example.com' } }));
    const { GET } = await import('../api/auth/session/route');
    const ok = await GET(req('/api/auth/session', { headers: { cookie: `${ACCESS_COOKIE}=alpha-access-token-12345` } }));
    expect(ok.status).toBe(200);
    expect(await ok.json()).toMatchObject({ authenticated: true, mode: 'private_alpha', user: { id: 'user-alpha', email: 'alpha@example.com' } });
    expect(fetcher).toHaveBeenCalledWith(new URL('/auth/session', 'http://api:8000'), expect.objectContaining({
      method: 'GET',
      headers: expect.objectContaining({ authorization: 'Bearer alpha-access-token-12345', 'x-internal-api-key': internalKey }),
    }));

    vi.resetModules();
    setup();
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(Response.json({ error: { code: 'expired' } }, { status: 401 }));
    const expired = await (await import('../api/auth/session/route')).GET(req('/api/auth/session', { headers: { cookie: `${ACCESS_COOKIE}=expired-token` } }));
    expect(expired.status).toBe(401);
    expect((await expired.json()).error.code).toBe('AUTH_REQUIRED');
    expect(expired.headers.get('set-cookie')).toContain('Max-Age=0');
  });

  it('fails closed on wrong origins and upstream auth outages', async () => {
    const fetcher = vi.spyOn(globalThis, 'fetch');
    const { POST } = await import('../api/auth/login/route');
    const wrongOrigin = await POST(req('/api/auth/login', {
      method: 'POST',
      headers: { origin: 'https://evil.example.com', 'content-type': 'application/json' },
      body: JSON.stringify({ email: 'a@example.com', password: 'valid-alpha-password' }),
    }));
    expect(wrongOrigin.status).toBe(403);
    expect(fetcher).not.toHaveBeenCalled();

    vi.resetModules();
    setup();
    vi.spyOn(globalThis, 'fetch').mockRejectedValue(new Error('secret backend stack'));
    const outage = await (await import('../api/auth/session/route')).GET(req('/api/auth/session', { headers: { cookie: `${ACCESS_COOKIE}=alpha-access-token-12345` } }));
    expect(outage.status).toBe(503);
    const body = await outage.text();
    expect(body).toContain('AUTH_PROVIDER_UNAVAILABLE');
    expect(body).not.toContain('secret');
    expect(outage.headers.get('set-cookie') ?? '').not.toContain('Max-Age=0');
  });

  it('calls Python logout for valid alpha cookies and does not clear cookies on upstream outage', async () => {
    const fetcher = vi.spyOn(globalThis, 'fetch').mockResolvedValue(Response.json({ ok: true }));
    const { POST } = await import('../api/auth/logout/route');
    const ok = await POST(req('/api/auth/logout', { method: 'POST', headers: { origin, cookie: `${ACCESS_COOKIE}=alpha-access-token-12345` } }));
    expect(ok.status).toBe(200);
    expect(fetcher).toHaveBeenCalledWith(new URL('/auth/logout', 'http://api:8000'), expect.objectContaining({
      method: 'POST',
      headers: expect.objectContaining({ authorization: 'Bearer alpha-access-token-12345', 'x-internal-api-key': internalKey }),
    }));
    expect(ok.headers.get('set-cookie')).toContain('Max-Age=0');

    vi.resetModules();
    setup();
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(Response.json({ error: { code: 'down' } }, { status: 503 }));
    const down = await (await import('../api/auth/logout/route')).POST(req('/api/auth/logout', { method: 'POST', headers: { origin, cookie: `${ACCESS_COOKIE}=alpha-access-token-12345` } }));
    expect(down.status).toBe(503);
    expect(down.headers.get('set-cookie') ?? '').not.toContain('Max-Age=0');
  });

  it('does not call Python logout with a planted localhost cookie on HTTPS alpha', async () => {
    const fetcher = vi.spyOn(globalThis, 'fetch');
    const { POST } = await import('../api/auth/logout/route');
    const res = await POST(req('/api/auth/logout', { method: 'POST', headers: { origin, cookie: `${LOCAL_ALPHA_ACCESS_COOKIE}=planted-parent-domain-token` } }));
    expect(res.status).toBe(200);
    expect(await res.json()).toEqual({ ok: true });
    expect(fetcher).not.toHaveBeenCalled();
    expect(res.headers.get('set-cookie')).toContain('Max-Age=0');
  });

  it('changes password through Python after session validation and signs out locally', async () => {
    const fetcher = vi.spyOn(globalThis, 'fetch')
      .mockResolvedValueOnce(Response.json({ user: { id: 'user-alpha', email: 'alpha@example.com' } }))
      .mockResolvedValueOnce(Response.json({ ok: true }));
    const { POST } = await import('../api/auth/password/route');
    const res = await POST(req('/api/auth/password', {
      method: 'POST',
      headers: { origin, cookie: `${ACCESS_COOKIE}=alpha-access-token-12345`, 'content-type': 'application/json' },
      body: JSON.stringify({ currentPassword: 'current-pass-123', newPassword: 'new-strong-pass-456' }),
    }));
    expect(res.status).toBe(200);
    expect(await res.json()).toEqual({ ok: true, authenticated: false });
    expect(fetcher).toHaveBeenNthCalledWith(1, new URL('/auth/session', 'http://api:8000'), expect.any(Object));
    expect(fetcher).toHaveBeenNthCalledWith(2, new URL('/auth/password', 'http://api:8000'), expect.objectContaining({
      method: 'POST',
      headers: expect.objectContaining({ authorization: 'Bearer alpha-access-token-12345', 'x-internal-api-key': internalKey }),
    }));
    expect(res.headers.get('set-cookie')).toContain('Max-Age=0');
  });

  it('keeps the session when password change rejects only the current password', async () => {
    vi.spyOn(globalThis, 'fetch')
      .mockResolvedValueOnce(Response.json({ user: { id: 'user-alpha', email: 'alpha@example.com' } }))
      .mockResolvedValueOnce(Response.json({ error: { code: 'AUTH_INVALID', message: 'wrong current password' } }, { status: 401 }));
    const { POST } = await import('../api/auth/password/route');
    const res = await POST(req('/api/auth/password', {
      method: 'POST',
      headers: { origin, cookie: `${ACCESS_COOKIE}=alpha-access-token-12345`, 'content-type': 'application/json' },
      body: JSON.stringify({ currentPassword: 'wrong-current-123', newPassword: 'new-strong-pass-456' }),
    }));
    expect(res.status).toBe(401);
    const body = await res.json();
    expect(body.error.code).toBe('AUTH_PASSWORD_INVALID');
    expect(body.error.message).toContain('Current password is incorrect');
    expect(res.headers.get('set-cookie') ?? '').not.toContain('Max-Age=0');
  });

  it('preserves the session when password change returns upstream format validation', async () => {
    vi.spyOn(globalThis, 'fetch')
      .mockResolvedValueOnce(Response.json({ user: { id: 'user-alpha', email: 'alpha@example.com' } }))
      .mockResolvedValueOnce(Response.json({ error: { code: 'PASSWORD_INVALID', message: 'backend format detail' } }, { status: 400 }));
    const { POST } = await import('../api/auth/password/route');
    const res = await POST(req('/api/auth/password', {
      method: 'POST',
      headers: { origin, cookie: `${ACCESS_COOKIE}=alpha-access-token-12345`, 'content-type': 'application/json' },
      body: JSON.stringify({ currentPassword: 'current-pass-123', newPassword: 'new-strong-pass-456' }),
    }));
    expect(res.status).toBe(400);
    const body = await res.json();
    expect(body.error.code).toBe('AUTH_PASSWORD_INVALID');
    expect(body.error.message).toContain('required format and length');
    expect(body.error.message).not.toContain('backend format detail');
    expect(res.headers.get('set-cookie') ?? '').not.toContain('Max-Age=0');
  });

  it('preserves the session and status when password changes are rate limited', async () => {
    vi.spyOn(globalThis, 'fetch')
      .mockResolvedValueOnce(Response.json({ user: { id: 'user-alpha', email: 'alpha@example.com' } }))
      .mockResolvedValueOnce(Response.json({ error: { code: 'RATE_LIMITED', message: 'internal rate budget' } }, { status: 429 }));
    const { POST } = await import('../api/auth/password/route');
    const res = await POST(req('/api/auth/password', {
      method: 'POST',
      headers: { origin, cookie: `${ACCESS_COOKIE}=alpha-access-token-12345`, 'content-type': 'application/json' },
      body: JSON.stringify({ currentPassword: 'current-pass-123', newPassword: 'new-strong-pass-456' }),
    }));
    expect(res.status).toBe(429);
    const body = await res.json();
    expect(body.error.code).toBe('AUTH_RATE_LIMITED');
    expect(body.error.message).toContain('Wait and try again');
    expect(res.headers.get('set-cookie') ?? '').not.toContain('Max-Age=0');
  });

  it('clears the session when password change sees an actually expired session', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(Response.json({ error: { code: 'expired' } }, { status: 401 }));
    const { POST } = await import('../api/auth/password/route');
    const res = await POST(req('/api/auth/password', {
      method: 'POST',
      headers: { origin, cookie: `${ACCESS_COOKIE}=expired-token`, 'content-type': 'application/json' },
      body: JSON.stringify({ currentPassword: 'current-pass-123', newPassword: 'new-strong-pass-456' }),
    }));
    expect(res.status).toBe(401);
    expect((await res.json()).error.code).toBe('AUTH_REQUIRED');
    expect(res.headers.get('set-cookie')).toContain('Max-Age=0');
  });

  it('clears the session when a validated password change token expires before mutation', async () => {
    vi.spyOn(globalThis, 'fetch')
      .mockResolvedValueOnce(Response.json({ user: { id: 'user-alpha', email: 'alpha@example.com' } }))
      .mockResolvedValueOnce(Response.json({ error: { code: 'AUTH_REQUIRED', message: 'expired before mutation' } }, { status: 401 }));
    const { POST } = await import('../api/auth/password/route');
    const res = await POST(req('/api/auth/password', {
      method: 'POST',
      headers: { origin, cookie: `${ACCESS_COOKIE}=alpha-access-token-12345`, 'content-type': 'application/json' },
      body: JSON.stringify({ currentPassword: 'current-pass-123', newPassword: 'new-strong-pass-456' }),
    }));
    expect(res.status).toBe(401);
    expect((await res.json()).error.code).toBe('AUTH_REQUIRED');
    expect(res.headers.get('set-cookie')).toContain('Max-Age=0');
  });
});
