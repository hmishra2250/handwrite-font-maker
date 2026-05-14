import { NextResponse } from 'next/server';
import { isLiveMode, isLocalMode, workerBaseUrl } from '@/lib/contracts';
import { demoMarkerFailure, demoSuccessJob } from '@/lib/mock-jobs';

/**
 * Rewrite `local://download/<key>` artifact URLs into direct Python backend
 * URLs so the browser can fetch them (the Python server serves CORS headers).
 */
function rewriteLocalArtifactUrls(payload: Record<string, unknown>): Record<string, unknown> {
  const artifacts = payload.artifacts;
  if (!Array.isArray(artifacts)) return payload;
  const base = workerBaseUrl();
  return {
    ...payload,
    artifacts: artifacts.map((a: Record<string, unknown>) => {
      const url = typeof a.url === 'string' ? a.url : '';
      if (url.startsWith('local://download/')) {
        const objectKey = url.replace('local://download/', '').split('?')[0];
        return { ...a, url: `${base}/objects/${objectKey}` };
      }
      const objectKey = typeof a.object_key === 'string' ? a.object_key : typeof a.objectKey === 'string' ? a.objectKey : '';
      if (!url && objectKey) {
        return { ...a, url: `${base}/objects/${objectKey}` };
      }
      return a;
    }),
  };
}

export async function GET(_request: Request, { params }: { params: Promise<{ jobId: string }> }) {
  const { jobId } = await params;

  /* --- Local or Live mode: proxy to the Python backend --- */
  if (isLocalMode() || isLiveMode()) {
    const base = workerBaseUrl();
    if (!base) {
      return NextResponse.json({ error: { code: 'INTERNAL_ERROR', message: 'Worker API URL is not configured.' } }, { status: 500 });
    }
    const upstream = await fetch(new URL(`/jobs/${encodeURIComponent(jobId)}`, base), { cache: 'no-store' });
    let payload: Record<string, unknown> = await upstream.json().catch(() => ({ error: { code: 'INTERNAL_ERROR', message: 'Worker returned a non-JSON response.' } }));
    if (isLocalMode() && upstream.ok) {
      payload = rewriteLocalArtifactUrls(payload);
    }
    return NextResponse.json(payload, { status: upstream.status });
  }

  /* --- Demo mode: canned responses --- */
  const payload = jobId.includes('fail') ? demoMarkerFailure : { ...demoSuccessJob, jobId };
  return NextResponse.json(payload);
}
