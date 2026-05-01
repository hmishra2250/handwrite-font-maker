import { NextResponse } from 'next/server';
import { randomUUID } from 'node:crypto';
import { isLiveMode, isSupportedImage, MAX_UPLOAD_BYTES, retentionExpiry, type UploadRequest, type UploadResponse } from '@/lib/contracts';
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

  const extension = body.filename.split('.').pop()?.toLowerCase()?.replace(/[^a-z0-9]/g, '') || 'jpg';
  const jobId = `job_${randomUUID()}`;
  const objectKey = `jobs/${jobId}/input/original.${extension}`;
  const bucket = storageBucket();

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
