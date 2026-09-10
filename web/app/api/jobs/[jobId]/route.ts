import { NextResponse } from 'next/server';
import { isLiveMode, isLocalMode } from '@/lib/contracts';
import { demoBackendUnavailable, demoMarkerFailure } from '@/lib/mock-jobs';
import { applyAuthCookies, authenticatedWorkerHeaders, enforceMutationOrigin, protectedWorkerBaseUrl, requireAuthenticatedRequest, sanitizeProtectedWorkerError } from '@/lib/server-auth';

/**
 * Rewrite `local://download/<key>` artifact URLs into same-origin object
 * proxy URLs so browser fetches do not depend on Docker-internal hostnames.
 */
function rewriteLocalArtifactUrls(payload: Record<string, unknown>): Record<string, unknown> {
  const artifacts = payload.artifacts;
  if (!Array.isArray(artifacts)) return payload;
  return {
    ...payload,
    artifacts: artifacts.map((a: Record<string, unknown>) => {
      const url = typeof a.url === 'string' ? a.url : '';
      if (url.startsWith('local://download/')) {
        const objectKey = url.replace('local://download/', '').split('?')[0];
        return { ...a, url: `/api/objects/${objectKey}` };
      }
      const objectKey = typeof a.object_key === 'string' ? a.object_key : typeof a.objectKey === 'string' ? a.objectKey : '';
      if (!url && objectKey) {
        return { ...a, url: `/api/objects/${objectKey}` };
      }
      return a;
    }),
  };
}

export async function GET(_request: Request, { params }: { params: Promise<{ jobId: string }> }) {
  const { jobId } = await params;
  const authResult = await requireAuthenticatedRequest(_request);
  if (!authResult.ok) return authResult.response;
  const auth = authResult.auth;
  const json = (body: unknown, init?: ResponseInit) => applyAuthCookies(NextResponse.json(body, init), auth);

  /* --- Local or Live mode: proxy to the Python backend --- */
  if (auth.protected || isLocalMode() || isLiveMode()) {
    const base = protectedWorkerBaseUrl(auth);
    if (!base) {
      return json({ error: { code: 'INTERNAL_ERROR', message: 'Worker API URL is not configured.' } }, { status: 500 });
    }
    const upstream = await fetch(new URL(`/jobs/${encodeURIComponent(jobId)}`, base), { headers: authenticatedWorkerHeaders(auth), cache: 'no-store' });
    let payload: Record<string, unknown> = await upstream.json().catch(() => ({ error: { code: 'INTERNAL_ERROR', message: 'Worker returned a non-JSON response.' } }));
    if ((auth.protected || isLocalMode()) && upstream.ok) {
      payload = rewriteLocalArtifactUrls(payload);
    }
    const safePayload = upstream.ok ? payload : sanitizeProtectedWorkerError(auth, payload, 'Job lookup failed.');
    return applyAuthCookies(NextResponse.json(safePayload, { status: upstream.status }), auth);
  }

  /* --- Demo mode: canned responses --- */
  const payload = jobId.includes('fail') ? demoMarkerFailure : { ...demoBackendUnavailable, jobId };
  return NextResponse.json(payload);
}

export async function DELETE(request: Request, { params }: { params: Promise<{ jobId: string }> }) {
  const originError = enforceMutationOrigin(request);
  if (originError) return originError;
  const authResult = await requireAuthenticatedRequest(request);
  if (!authResult.ok) return authResult.response;
  const auth = authResult.auth;
  const json = (body: unknown, init?: ResponseInit) => applyAuthCookies(NextResponse.json(body, init), auth);
  const { jobId } = await params;

  if (!(auth.protected || isLocalMode() || isLiveMode())) {
    return json({ error: { code: 'INTERNAL_ERROR', message: 'Job deletion requires a configured Python worker.' } }, { status: 503 });
  }
  const base = protectedWorkerBaseUrl(auth);
  if (!base) {
    return json({ error: { code: 'INTERNAL_ERROR', message: 'Worker API URL is not configured.' } }, { status: 500 });
  }
  const upstream = await fetch(new URL(`/jobs/${encodeURIComponent(jobId)}`, base), {
    method: 'DELETE',
    headers: authenticatedWorkerHeaders(auth),
    cache: 'no-store',
  });
  const payload: unknown = upstream.status === 204 ? { ok: true } : await upstream.json().catch(() => ({ error: { code: 'INTERNAL_ERROR', message: 'Worker returned a non-JSON response.' } }));
  const safePayload = upstream.ok ? payload : sanitizeProtectedWorkerError(auth, payload, 'Job deletion failed.');
  return applyAuthCookies(NextResponse.json(safePayload, { status: upstream.status === 204 ? 200 : upstream.status }), auth);
}
