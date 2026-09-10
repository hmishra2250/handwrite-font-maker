import { readBoundedJson } from '@/lib/read-json';
import { NextResponse } from 'next/server';
import { ERROR_COPY, isLiveMode, isLocalMode, isSafeFontName, retentionExpiry, validateCaptureConfig, type CreateJobRequest, type JobResponse } from '@/lib/contracts';
import { demoBackendUnavailable } from '@/lib/mock-jobs';
import { applyAuthCookies, authenticatedWorkerHeaders, enforceMutationOrigin, protectedWorkerBaseUrl, requireAuthenticatedRequest, sanitizeProtectedWorkerError } from '@/lib/server-auth';

export async function POST(request: Request) {
  const originError = enforceMutationOrigin(request);
  if (originError) return originError;
  const authResult = await requireAuthenticatedRequest(request);
  if (!authResult.ok) return authResult.response;
  const auth = authResult.auth;
  const json = (body: unknown, init?: ResponseInit) => applyAuthCookies(NextResponse.json(body, init), auth);
  const body = (await readBoundedJson(request)) as CreateJobRequest | null;
  if (!body?.inputPhoto?.objectKey) {
    return json({ error: { code: 'UPLOAD_OBJECT_MISSING', message: ERROR_COPY.UPLOAD_OBJECT_MISSING } }, { status: 400 });
  }
  if (!body.font?.fontName || !isSafeFontName(body.font.fontName)) {
    return json({ error: { code: 'FONT_METADATA_INVALID', message: ERROR_COPY.FONT_METADATA_INVALID } }, { status: 400 });
  }
  const captureError = validateCaptureConfig(body.capture);
  if (captureError) {
    return json({ error: { code: 'CAPTURE_CONFIG_INVALID', message: captureError } }, { status: 400 });
  }

  /* --- Local or Live mode: proxy to the Python backend --- */
  if (auth.protected || isLocalMode() || isLiveMode()) {
    const base = protectedWorkerBaseUrl(auth);
    if (!base) {
      return json({ error: { code: 'INTERNAL_ERROR', message: 'Worker API URL is not configured.' } }, { status: 500 });
    }

    const upstream = await fetch(new URL('/jobs', base), {
      method: 'POST',
      headers: authenticatedWorkerHeaders(auth, { 'content-type': 'application/json' }),
      body: JSON.stringify(body),
      cache: 'no-store'
    });
    const payload: unknown = await upstream.json().catch(() => ({ error: { code: 'INTERNAL_ERROR', message: 'Worker returned a non-JSON response.' } }));
    const safePayload = upstream.ok ? payload : sanitizeProtectedWorkerError(auth, payload, 'Job creation failed.');
    return applyAuthCookies(NextResponse.json(safePayload, { status: upstream.status }), auth);
  }

  /* --- Demo mode: return canned response --- */
  const response: JobResponse = {
    ...demoBackendUnavailable,
    jobId: body.inputPhoto.objectKey.split('/')[1] ?? demoBackendUnavailable.jobId,
    status: 'queued',
    stage: 'queued',
    progressLabel: 'Demo mode prepared the job envelope only. Configure WORKER_API_BASE_URL to run a real build.',
    retentionExpiresAt: retentionExpiry()
  };
  return NextResponse.json(response, { status: 202 });
}
