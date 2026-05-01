import { NextResponse } from 'next/server';
import { ERROR_COPY, isLiveMode, isSafeFontName, retentionExpiry, type CreateJobRequest, type JobResponse } from '@/lib/contracts';
import { demoSuccessJob } from '@/lib/mock-jobs';

export async function POST(request: Request) {
  const body = (await request.json().catch(() => null)) as CreateJobRequest | null;
  if (!body?.inputPhoto?.objectKey) {
    return NextResponse.json({ error: { code: 'UPLOAD_OBJECT_MISSING', message: ERROR_COPY.UPLOAD_OBJECT_MISSING } }, { status: 400 });
  }
  if (!body.font?.fontName || !isSafeFontName(body.font.fontName)) {
    return NextResponse.json({ error: { code: 'FONT_METADATA_INVALID', message: ERROR_COPY.FONT_METADATA_INVALID } }, { status: 400 });
  }

  if (!isLiveMode()) {
    const response: JobResponse = {
      ...demoSuccessJob,
      jobId: body.inputPhoto.objectKey.split('/')[1] ?? demoSuccessJob.jobId,
      status: 'queued',
      stage: 'queued',
      progressLabel: 'Demo mode queued the sample job. Configure Render and Supabase to run live builds.',
      artifacts: [],
      warnings: [],
      retentionExpiresAt: retentionExpiry()
    };
    return NextResponse.json(response, { status: 202 });
  }

  const workerBase = process.env.WORKER_API_BASE_URL;
  if (!workerBase) {
    return NextResponse.json({ error: { code: 'INTERNAL_ERROR', message: 'Worker API URL is not configured.' } }, { status: 500 });
  }

  const upstream = await fetch(new URL('/jobs', workerBase), {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify(body),
    cache: 'no-store'
  });
  const payload: unknown = await upstream.json().catch(() => ({ error: { code: 'INTERNAL_ERROR', message: 'Worker returned a non-JSON response.' } }));
  return NextResponse.json(payload, { status: upstream.status });
}
