import { readBoundedJson } from '@/lib/read-json';
import { NextResponse } from 'next/server';
import { randomUUID } from 'node:crypto';
import { isLiveMode, isLocalMode, isSupportedImage, MAX_UPLOAD_BYTES, retentionExpiry, type UploadRequest, type UploadResponse } from '@/lib/contracts';
import { applyAuthCookies, authenticatedWorkerHeaders, enforceMutationOrigin, protectedWorkerBaseUrl, requireAuthenticatedRequest, sanitizeProtectedWorkerError } from '@/lib/server-auth';
import { getSupabaseAdmin, storageBucket } from '@/lib/supabase-server';

export async function POST(request: Request) {
  const originError = enforceMutationOrigin(request);
  if (originError) return originError;
  const authResult = await requireAuthenticatedRequest(request);
  if (!authResult.ok) return authResult.response;
  const auth = authResult.auth;
  const json = (body: unknown, init?: ResponseInit) => applyAuthCookies(NextResponse.json(body, init), auth);
  const body = (await readBoundedJson(request)) as UploadRequest | null;
  if (!body?.filename || !body.contentType || !body.sizeBytes) {
    return json({ error: { code: 'UPLOAD_OBJECT_MISSING', message: 'filename, contentType, and sizeBytes are required.' } }, { status: 400 });
  }
  if (!isSupportedImage(body.contentType)) {
    return json({ error: { code: 'UNSUPPORTED_IMAGE_TYPE', message: 'Upload a JPEG, PNG, or WebP image.' } }, { status: 415 });
  }
  if (body.sizeBytes > MAX_UPLOAD_BYTES) {
    return json({ error: { code: 'UPLOAD_OBJECT_TOO_LARGE', message: `Upload must be ${MAX_UPLOAD_BYTES} bytes or smaller.` } }, { status: 413 });
  }

  /* --- Local mode: proxy upload-slot creation to the Python backend.
         The browser PUTs bytes to a same-origin object proxy so Docker-only hostnames are not exposed. --- */
  if (auth.protected || isLocalMode()) {
    const base = protectedWorkerBaseUrl(auth);
    const upstream = await fetch(new URL('/uploads', base), {
      method: 'POST',
      headers: authenticatedWorkerHeaders(auth, { 'content-type': 'application/json' }),
      body: JSON.stringify(body),
      cache: 'no-store',
    });
    const payload = (await upstream.json().catch(() => null)) as Record<string, unknown> | null;
    if (!upstream.ok) {
      return json(sanitizeProtectedWorkerError(auth, payload ?? { error: { code: 'INTERNAL_ERROR' } }, 'Upload slot creation failed.'), { status: upstream.status });
    }
    const objectKeyValue = payload?.objectKey ?? payload?.object_key;
    if (typeof objectKeyValue !== 'string' || objectKeyValue.length < 1) {
      return json({ error: { code: 'UPLOAD_OBJECT_MISSING', message: 'Worker upload-slot response did not include an object key.' } }, { status: 502 });
    }
    const response: UploadResponse = {
      mode: 'local',
      uploadUrl: `/api/objects/${objectKeyValue}`,
      method: 'PUT',
      objectKey: objectKeyValue,
      expiresAt: typeof payload?.expiresAt === 'string' ? payload.expiresAt : retentionExpiry(1),
      maxUploadBytes: MAX_UPLOAD_BYTES,
    };
    return applyAuthCookies(NextResponse.json(response), auth);
  }

  const extension = body.filename.split('.').pop()?.toLowerCase()?.replace(/[^a-z0-9]/g, '') || 'jpg';
  const jobId = `job_${randomUUID()}`;
  const objectKey = `jobs/${jobId}/input/original.${extension}`;
  const bucket = storageBucket();

  /* --- Demo mode: no backend at all --- */
  if (!isLiveMode()) {
    const response: UploadResponse = {
      mode: 'demo',
      uploadUrl: `/api/uploads/demo/${encodeURIComponent(objectKey)}`,
      method: 'PUT',
      objectKey,
      bucket,
      expiresAt: retentionExpiry(1),
      maxUploadBytes: MAX_UPLOAD_BYTES
    };
    return NextResponse.json(response);
  }

  /* --- Live / cloud mode: Supabase signed upload --- */
  const supabase = getSupabaseAdmin();
  if (!supabase) {
    return NextResponse.json({ error: { code: 'INTERNAL_ERROR', message: 'Supabase is not configured.' } }, { status: 500 });
  }

  const { data, error } = await supabase.storage.from(bucket).createSignedUploadUrl(objectKey);
  if (error || !data?.signedUrl) {
    return NextResponse.json({ error: { code: 'INTERNAL_ERROR', message: error?.message ?? 'Could not create signed upload URL.' } }, { status: 500 });
  }

  const response: UploadResponse = {
    mode: 'live',
    uploadUrl: data.signedUrl,
    method: 'PUT',
    objectKey,
    bucket,
    expiresAt: retentionExpiry(1),
    maxUploadBytes: MAX_UPLOAD_BYTES
  };
  return NextResponse.json(response);
}
