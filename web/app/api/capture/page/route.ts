import { readBoundedJson } from '@/lib/read-json';
import { NextResponse } from 'next/server';
import { ERROR_COPY, isLiveMode, isLocalMode, isValidPageCorners, type CapturePageRequest, type CapturePageResponse } from '@/lib/contracts';
import { applyAuthCookies, authenticatedWorkerHeaders, enforceMutationOrigin, protectedWorkerBaseUrl, requireAuthenticatedRequest, sanitizeProtectedWorkerError } from '@/lib/server-auth';

export async function POST(request: Request) {
  const originError = enforceMutationOrigin(request);
  if (originError) return originError;
  const authResult = await requireAuthenticatedRequest(request);
  if (!authResult.ok) return authResult.response;
  const auth = authResult.auth;
  const json = (body: unknown, init?: ResponseInit) => applyAuthCookies(NextResponse.json(body, init), auth);
  const body = (await readBoundedJson(request)) as CapturePageRequest | null;
  if (!body?.inputPhoto?.objectKey) {
    return json({ error: { code: 'UPLOAD_OBJECT_MISSING', message: ERROR_COPY.UPLOAD_OBJECT_MISSING } }, { status: 400 });
  }

  if (!(auth.protected || isLocalMode() || isLiveMode())) {
    return json(
      {
        error: {
          code: 'INTERNAL_ERROR',
          message: 'Page-corner detection requires a configured Python worker. You can still enter corners manually before running a real local/staging build.',
        },
      },
      { status: 503 },
    );
  }

  const base = protectedWorkerBaseUrl(auth);
  if (!base) {
    return json({ error: { code: 'INTERNAL_ERROR', message: 'Worker API URL is not configured.' } }, { status: 500 });
  }

  const upstream = await fetch(new URL('/capture/page', base), {
    method: 'POST',
    headers: authenticatedWorkerHeaders(auth, { 'content-type': 'application/json' }),
    body: JSON.stringify(body),
    cache: 'no-store',
  });
  const payload: unknown = await upstream.json().catch(() => ({ error: { code: 'INTERNAL_ERROR', message: 'Worker returned a non-JSON response.' } }));
  if (!upstream.ok) {
    return applyAuthCookies(NextResponse.json(sanitizeProtectedWorkerError(auth, payload, 'Page-corner detection failed.'), { status: upstream.status }), auth);
  }

  const corners = (payload as CapturePageResponse).corners;
  if (!isValidPageCorners(corners)) {
    return json({ error: { code: 'CAPTURE_CONFIG_INVALID', message: 'Worker returned invalid page corners.' } }, { status: 502 });
  }

  return applyAuthCookies(NextResponse.json({ corners } satisfies CapturePageResponse, { status: upstream.status }), auth);
}
