import { readBoundedJson } from '@/lib/read-json';
import { applyAuthCookies, authenticatedWorkerHeaders, enforceMutationOrigin, noStoreResponse, protectedWorkerBaseUrl, requireAuthenticatedRequest } from '@/lib/server-auth';
import { NextResponse } from 'next/server';

export async function POST(request: Request) {
  const originError = enforceMutationOrigin(request);
  if (originError) return originError;
  const authResult = await requireAuthenticatedRequest(request);
  if (!authResult.ok) return authResult.response;
  const auth = authResult.auth;
  const json = (body: unknown, init?: ResponseInit) => noStoreResponse(applyAuthCookies(NextResponse.json(body, init), auth));
  const body = (await readBoundedJson(request, 2048)) as { offerId?: unknown } | null;
  if (!body || typeof body !== 'object' || Array.isArray(body)) {
    return json({ error: { code: 'BILLING_REQUEST_INVALID', message: 'A bounded JSON object is required.' } }, { status: 400 });
  }
  const base = protectedWorkerBaseUrl(auth);
  if (!base) {
    return json({ error: { code: 'BILLING_UNAVAILABLE', message: 'Checkout is temporarily unavailable.' } }, { status: 503 });
  }
  try {
    const upstream = await fetch(new URL('/billing/checkout', base), {
      method: 'POST',
      headers: authenticatedWorkerHeaders(auth, { 'content-type': 'application/json' }),
      body: JSON.stringify({ offerId: body.offerId }),
      cache: 'no-store',
      signal: AbortSignal.timeout(10_000),
    });
    const payload = await upstream.json().catch(() => ({ error: { code: 'BILLING_UNAVAILABLE', message: 'Checkout is temporarily unavailable.' } }));
    if (upstream.status >= 500 && (payload as { error?: { code?: unknown } })?.error?.code !== 'PAYMENT_NOT_CONFIGURED') {
      return json({ error: { code: 'BILLING_UNAVAILABLE', message: 'Checkout is temporarily unavailable.' } }, { status: 503 });
    }
    return json(payload, { status: upstream.status });
  } catch {
    return json({ error: { code: 'BILLING_UNAVAILABLE', message: 'Checkout is temporarily unavailable.' } }, { status: 503 });
  }
}
