import { NextResponse } from 'next/server';
import { randomUUID } from 'node:crypto';
import { isLiveMode, isLocalMode, isSupportedImage, MAX_UPLOAD_BYTES, retentionExpiry, workerBaseUrl, type UploadRequest, type UploadResponse } from '@/lib/contracts';
import { getSupabaseAdmin, storageBucket } from '@/lib/supabase-server';

export async function POST(request: Request) {
  const body = (await request.json().catch(() => null)) as UploadRequest | null;
  if (!body?.filename || !body.contentType || !body.sizeBytes) {
    return NextResponse.json({ error: { code: 'UPLOAD_OBJECT_MISSING', message: 'filename, contentType, and sizeBytes are required.' } }, { status: 400 });
  }
  if (!isSupportedImage(body.contentType)) {
    return NextResponse.json({ error: { code: 'UNSUPPORTED_IMAGE_TYPE', message: 'Upload a JPEG, PNG, or WebP image.' } }, { status: 415 });
  }
  if (body.sizeBytes > MAX_UPLOAD_BYTES) {
    return NextResponse.json({ error: { code: 'UPLOAD_OBJECT_TOO_LARGE', message: `Upload must be ${MAX_UPLOAD_BYTES} bytes or smaller.` } }, { status: 413 });
  }

  /* --- Local mode: proxy upload-slot creation to the Python backend.
         The client will PUT the file bytes directly to the Python server. --- */
  if (isLocalMode()) {
    const base = workerBaseUrl();
    const upstream = await fetch(new URL('/uploads', base), {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify(body),
      cache: 'no-store',
    });
    const payload = (await upstream.json()) as Record<string, unknown>;
    const objectKey = String(payload.objectKey ?? '');
    const response: UploadResponse = {
      mode: 'local',
      /* Direct URL to the Python backend -- CORS is handled there. */
      uploadUrl: `${base}/objects/${objectKey}`,
      method: 'PUT',
      objectKey,
      expiresAt: String(payload.expiresAt ?? retentionExpiry(1)),
      maxUploadBytes: MAX_UPLOAD_BYTES,
    };
    return NextResponse.json(response);
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
