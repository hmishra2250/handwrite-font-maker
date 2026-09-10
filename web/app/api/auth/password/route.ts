import { readBoundedJson } from '@/lib/read-json';
import { NextResponse } from 'next/server';
import { clearSessionCookies, deploymentMode, enforceMutationOrigin, noStoreResponse, protectedWorkerBaseUrl, requireAuthenticatedRequest } from '@/lib/server-auth';

function passwordUtf8Bytes(value: string) {
  return new TextEncoder().encode(value).byteLength;
}

function validatePassword(value: unknown) {
  if (typeof value !== 'string') return false;
  return value.length >= 12 && value.length <= 256 && passwordUtf8Bytes(value) <= 1024;
}

export async function POST(request: Request) {
  const originError = enforceMutationOrigin(request);
  if (originError) return originError;
  if (deploymentMode() !== 'private_alpha') {
    return noStoreResponse(NextResponse.json({ error: { code: 'AUTH_PASSWORD_UNAVAILABLE', message: 'Password changes are only available for private alpha accounts.' } }, { status: 404 }));
  }
  const authResult = await requireAuthenticatedRequest(request);
  if (!authResult.ok) return authResult.response;
  const auth = authResult.auth;
  const body = (await readBoundedJson(request, 4096)) as { currentPassword?: unknown; newPassword?: unknown } | null;
  const currentPassword = body?.currentPassword;
  const newPassword = body?.newPassword;
  if (!validatePassword(currentPassword) || !validatePassword(newPassword)) {
    return noStoreResponse(NextResponse.json({ error: { code: 'AUTH_PASSWORD_INVALID', message: 'Current and new passwords must be 12–256 characters and at most 1024 UTF-8 bytes.' } }, { status: 400 }));
  }
  try {
    const upstream = await fetch(new URL('/auth/password', protectedWorkerBaseUrl(auth)), {
      method: 'POST',
      headers: { 'content-type': 'application/json', authorization: `Bearer ${auth.accessToken}`, 'x-internal-api-key': auth.config!.internalApiKey },
      body: JSON.stringify({ currentPassword, newPassword }),
      cache: 'no-store',
      signal: AbortSignal.timeout(10_000),
    });
    if (!upstream.ok) {
      const payload = await upstream.json().catch(() => null) as { error?: { code?: unknown } } | null;
      const upstreamCode = typeof payload?.error?.code === 'string' ? payload.error.code : '';
      if (upstream.status === 400) {
        return noStoreResponse(NextResponse.json({ error: { code: 'AUTH_PASSWORD_INVALID', message: 'Check your passwords meet the required format and length.' } }, { status: 400 }));
      }
      if (upstreamCode === 'AUTH_INVALID') {
        return noStoreResponse(NextResponse.json({ error: { code: 'AUTH_PASSWORD_INVALID', message: 'Current password is incorrect. Your session is still active.' } }, { status: 401 }));
      }
      if (upstream.status === 429) {
        return noStoreResponse(NextResponse.json({ error: { code: 'AUTH_RATE_LIMITED', message: 'Too many password attempts. Wait and try again.' } }, { status: 429 }));
      }
      if (upstream.status === 401 || upstream.status === 403) {
        const response = noStoreResponse(NextResponse.json({ error: { code: 'AUTH_REQUIRED', message: 'Sign in again to change your password.' } }, { status: 401 }));
        clearSessionCookies(response);
        return response;
      }
      return noStoreResponse(NextResponse.json({ error: { code: 'AUTH_PROVIDER_UNAVAILABLE', message: 'Authentication is temporarily unavailable. Try again.' } }, { status: 503 }));
    }
    const response = NextResponse.json({ ok: true, authenticated: false });
    clearSessionCookies(response);
    return noStoreResponse(response);
  } catch {
    return noStoreResponse(NextResponse.json({ error: { code: 'AUTH_PROVIDER_UNAVAILABLE', message: 'Authentication is temporarily unavailable. Try again.' } }, { status: 503 }));
  }
}
