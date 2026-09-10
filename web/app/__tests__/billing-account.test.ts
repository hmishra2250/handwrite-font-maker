import { beforeEach, describe, expect, it, vi } from 'vitest';
import { ACCESS_COOKIE } from '@/lib/server-auth';

const origin = 'https://alpha.example.com';
const internalKey = 'b'.repeat(40);

function setup() {
  vi.stubEnv('DEPLOYMENT_MODE', 'private_alpha');
  vi.stubEnv('SITE_URL', origin);
  vi.stubEnv('INTERNAL_API_KEY', internalKey);
  vi.stubEnv('WORKER_API_BASE_URL', 'http://api:8000');
}

function request(path: string, init: RequestInit = {}) {
  return new Request(`${origin}${path}`, init);
}

describe('alpha billing and account contracts', () => {
  beforeEach(() => {
    vi.resetModules();
    vi.restoreAllMocks();
    vi.unstubAllEnvs();
    setup();
  });

  it('serves a public disabled billing catalog with the proposed launch offers', async () => {
    const fetcher = vi.spyOn(globalThis, 'fetch').mockResolvedValue(Response.json({
      currency: 'USD',
      billingEnabled: false,
      offers: [
        { id: 'single', name: 'Make one font', priceCents: 1200, projects: 1 },
        { id: 'three_pack', name: 'Make three fonts', priceCents: 2900, projects: 3 },
      ],
      alpha: { name: 'Private alpha', priceCents: 0, inviteOnly: true },
      notice: 'Private alpha is free for invited accounts. Paid offers are planned, not available to purchase. No card is collected.',
    }));
    const { GET } = await import('../api/billing/catalog/route');
    const res = await GET();
    expect(res.status).toBe(200);
    const data = await res.json();
    expect(data).toMatchObject({ currency: 'USD', billingEnabled: false, alpha: { name: 'Private alpha', priceCents: 0, inviteOnly: true } });
    expect(data.offers).toEqual([
      { id: 'single', name: 'Make one font', priceCents: 1200, projects: 1 },
      { id: 'three_pack', name: 'Make three fonts', priceCents: 2900, projects: 3 },
    ]);
    expect(data.notice).toContain('Private alpha is free');
    expect(fetcher).toHaveBeenCalledWith(new URL('/billing/catalog', 'http://api:8000'), expect.objectContaining({ headers: expect.objectContaining({ 'x-internal-api-key': internalKey }) }));
    expect(res.headers.get('cache-control')).toBe('no-store');
  });

  it('requires same-origin authenticated checkout, validates offers, and returns PAYMENT_NOT_CONFIGURED', async () => {
    const fetcher = vi.spyOn(globalThis, 'fetch');
    const { POST } = await import('../api/billing/checkout/route');
    const wrongOrigin = await POST(request('/api/billing/checkout', {
      method: 'POST',
      headers: { origin: 'https://evil.example.com', cookie: `${ACCESS_COOKIE}=alpha-token-12345`, 'content-type': 'application/json' },
      body: JSON.stringify({ offerId: 'single' }),
    }));
    expect(wrongOrigin.status).toBe(403);
    expect(fetcher).not.toHaveBeenCalled();

    const missingAuth = await POST(request('/api/billing/checkout', {
      method: 'POST',
      headers: { origin, 'content-type': 'application/json' },
      body: JSON.stringify({ offerId: 'single' }),
    }));
    expect(missingAuth.status).toBe(401);
    expect(fetcher).not.toHaveBeenCalled();

    fetcher.mockImplementation(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.endsWith('/auth/session')) return Response.json({ user: { id: 'user-alpha', email: 'alpha@example.com' } });
      if (url.endsWith('/billing/checkout')) return Response.json({ error: { code: 'OFFER_INVALID', message: 'Choose a recognized offer.' } }, { status: 400 });
      throw new Error(`unexpected fetch ${url}`);
    });
    const badOffer = await POST(request('/api/billing/checkout', {
      method: 'POST',
      headers: { origin, cookie: `${ACCESS_COOKIE}=alpha-token-12345`, 'content-type': 'application/json' },
      body: JSON.stringify({ offerId: 'lifetime' }),
    }));
    expect(badOffer.status).toBe(400);

    fetcher.mockImplementation(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.endsWith('/auth/session')) return Response.json({ user: { id: 'user-alpha', email: 'alpha@example.com' } });
      if (url.endsWith('/billing/checkout')) return Response.json({ error: { code: 'PAYMENT_NOT_CONFIGURED', message: 'Payments are not enabled. Invited accounts can use the free private alpha; no charge was made.' } }, { status: 503 });
      throw new Error(`unexpected fetch ${url}`);
    });
    const disabled = await POST(request('/api/billing/checkout', {
      method: 'POST',
      headers: { origin, cookie: `${ACCESS_COOKIE}=alpha-token-12345`, 'content-type': 'application/json' },
      body: JSON.stringify({ offerId: 'three_pack' }),
    }));
    expect(disabled.status).toBe(503);
    expect((await disabled.json()).error.code).toBe('PAYMENT_NOT_CONFIGURED');
  });

  it('requires authentication for account details and returns alpha limits/retention', async () => {
    const fetcher = vi.spyOn(globalThis, 'fetch').mockImplementation(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.endsWith('/auth/session')) return Response.json({ user: { id: 'user-alpha', email: 'alpha@example.com' } });
      if (url.endsWith('/account')) return Response.json({
        user: { id: 'user-alpha', email: 'alpha@example.com' },
        plan: { id: 'private_alpha', name: 'Private alpha', billingEnabled: false },
        limits: { dailyUploads: 150, dailyUploadBytes: 209715200, dailyPreviews: 120, dailyBuilds: 5, activeJobs: 2 },
        retention: { projectDays: 7, downloadHours: 24 },
      });
      throw new Error(`unexpected fetch ${url}`);
    });
    const { GET } = await import('../api/account/route');
    const missing = await GET(request('/api/account'));
    expect(missing.status).toBe(401);
    const ok = await GET(request('/api/account', { headers: { cookie: `${ACCESS_COOKIE}=alpha-token-12345` } }));
    expect(ok.status).toBe(200);
    const data = await ok.json();
    expect(data).toMatchObject({
      user: { id: 'user-alpha', email: 'alpha@example.com' },
      plan: { id: 'private_alpha', name: 'Private alpha', billingEnabled: false },
      limits: { dailyUploads: 150, dailyUploadBytes: 209715200, dailyPreviews: 120, dailyBuilds: 5, activeJobs: 2 },
      retention: { projectDays: 7, downloadHours: 24 },
    });
    expect(fetcher).toHaveBeenCalledWith(new URL('/auth/session', 'http://api:8000'), expect.objectContaining({
      headers: expect.objectContaining({ authorization: 'Bearer alpha-token-12345', 'x-internal-api-key': internalKey }),
    }));
  });
});
