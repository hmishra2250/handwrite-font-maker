import { NextResponse } from 'next/server';
import { isLiveMode } from '@/lib/contracts';
import { demoMarkerFailure, demoSuccessJob } from '@/lib/mock-jobs';

export async function GET(_request: Request, { params }: { params: Promise<{ jobId: string }> }) {
  const { jobId } = await params;
  if (!isLiveMode()) {
    const payload = jobId.includes('fail') ? demoMarkerFailure : { ...demoSuccessJob, jobId };
    return NextResponse.json(payload);
  }

  const workerBase = process.env.WORKER_API_BASE_URL;
  if (!workerBase) {
    return NextResponse.json({ error: { code: 'INTERNAL_ERROR', message: 'Worker API URL is not configured.' } }, { status: 500 });
  }
  const upstream = await fetch(new URL(`/jobs/${encodeURIComponent(jobId)}`, workerBase), { cache: 'no-store' });
  const payload: unknown = await upstream.json().catch(() => ({ error: { code: 'INTERNAL_ERROR', message: 'Worker returned a non-JSON response.' } }));
  return NextResponse.json(payload, { status: upstream.status });
}
