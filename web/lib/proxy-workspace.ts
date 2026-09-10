import { NextResponse } from 'next/server';
import { readBoundedJson } from './read-json';
import { applyAuthCookies, authenticatedWorkerHeaders, enforceMutationOrigin, protectedWorkerBaseUrl, requireAuthenticatedRequest } from './server-auth';

/** New workspace endpoints share the existing server-only identity boundary. */
export async function proxyWorkspace(request: Request, path: string, method: 'GET' | 'POST' | 'PUT' | 'DELETE', maxBytes = 64 * 1024) {
  if (method !== 'GET') {
    const originError = enforceMutationOrigin(request);
    if (originError) return originError;
  }
  const result = await requireAuthenticatedRequest(request);
  if (!result.ok) return result.response;
  const { auth } = result;
  const json = (body: unknown, status: number) => applyAuthCookies(NextResponse.json(body, { status }), auth);
  const base = protectedWorkerBaseUrl(auth);
  if (!base) return json({ error: { code: 'BACKEND_UNAVAILABLE', message: 'Configure the Python backend to save your work.' } }, 503);
  let body: unknown;
  if (method === 'POST' || method === 'PUT') {
    body = await readBoundedJson(request, maxBytes);
    if (!body || typeof body !== 'object' || Array.isArray(body)) {
      return json({ error: { code: 'INVALID_REQUEST', message: 'A bounded JSON object is required.' } }, 400);
    }
  }
  try {
    const upstream = await fetch(new URL(path, base), {
      method,
      headers: authenticatedWorkerHeaders(auth, body ? { 'content-type': 'application/json' } : {}),
      body: body ? JSON.stringify(body) : undefined,
      cache: 'no-store',
      signal: AbortSignal.timeout(20_000),
    });
    const payload = await upstream.json();
    if (upstream.ok) return json(payload, upstream.status);
    const messages: Record<number, string> = {
      400: 'Check the project or feedback fields and try again.',
      401: 'Sign in again to continue.',
      403: 'This account cannot perform that action.',
      404: 'This item is missing or expired.',
      409: 'A newer project version exists. Reload it before saving; your current edits were not overwritten.',
      429: 'The beta safety limit was reached. Try again later.',
    };
    return json({ error: { code: upstream.status === 409 ? 'PROJECT_CONFLICT' : 'WORKSPACE_ERROR', message: messages[upstream.status] ?? 'Workspace storage is temporarily unavailable. Your changes are not saved.' } }, upstream.status);
  } catch {
    return json({ error: { code: 'BACKEND_UNAVAILABLE', message: 'Workspace storage is temporarily unavailable. Your changes are not saved.' } }, 503);
  }
}
