import { applyAuthCookies, authenticatedWorkerHeaders, noStoreResponse, protectedWorkerBaseUrl, requireAuthenticatedRequest } from '@/lib/server-auth';
import { NextResponse } from 'next/server';

export async function GET(request: Request) {
  const authResult = await requireAuthenticatedRequest(request);
  if (!authResult.ok) return authResult.response;
  const auth = authResult.auth;
  const base = protectedWorkerBaseUrl(auth);
  if (!base) {
    return noStoreResponse(applyAuthCookies(NextResponse.json({ error: { code: 'ACCOUNT_UNAVAILABLE', message: 'Account details are temporarily unavailable.' } }, { status: 503 }), auth));
  }
  try {
    const upstream = await fetch(new URL('/account', base), {
      method: 'GET',
      headers: authenticatedWorkerHeaders(auth),
      cache: 'no-store',
      signal: AbortSignal.timeout(10_000),
    });
    const payload = await upstream.json().catch(() => null);
    if (!upstream.ok || !payload) {
      return noStoreResponse(applyAuthCookies(NextResponse.json({ error: { code: 'ACCOUNT_UNAVAILABLE', message: 'Account details are temporarily unavailable.' } }, { status: 503 }), auth));
    }
    return noStoreResponse(applyAuthCookies(NextResponse.json(payload, { status: upstream.status }), auth));
  } catch {
    return noStoreResponse(applyAuthCookies(NextResponse.json({ error: { code: 'ACCOUNT_UNAVAILABLE', message: 'Account details are temporarily unavailable.' } }, { status: 503 }), auth));
  }
}
