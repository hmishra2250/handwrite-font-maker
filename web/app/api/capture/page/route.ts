import { NextResponse } from 'next/server';
import { ERROR_COPY, isLiveMode, isLocalMode, isValidPageCorners, workerBaseUrl, type CapturePageRequest, type CapturePageResponse } from '@/lib/contracts';

export async function POST(request: Request) {
  const body = (await request.json().catch(() => null)) as CapturePageRequest | null;
  if (!body?.inputPhoto?.objectKey) {
    return NextResponse.json({ error: { code: 'UPLOAD_OBJECT_MISSING', message: ERROR_COPY.UPLOAD_OBJECT_MISSING } }, { status: 400 });
  }

  if (!(isLocalMode() || isLiveMode())) {
    return NextResponse.json(
      {
        error: {
          code: 'INTERNAL_ERROR',
          message: 'Page-corner detection requires a configured Python worker. You can still enter corners manually before running a real local/staging build.',
        },
      },
      { status: 503 },
    );
  }

  const base = workerBaseUrl();
  if (!base) {
    return NextResponse.json({ error: { code: 'INTERNAL_ERROR', message: 'Worker API URL is not configured.' } }, { status: 500 });
  }

  const upstream = await fetch(new URL('/capture/page', base), {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify(body),
    cache: 'no-store',
  });
  const payload: unknown = await upstream.json().catch(() => ({ error: { code: 'INTERNAL_ERROR', message: 'Worker returned a non-JSON response.' } }));
  if (!upstream.ok) {
    return NextResponse.json(payload, { status: upstream.status });
  }

  const corners = (payload as CapturePageResponse).corners;
  if (!isValidPageCorners(corners)) {
    return NextResponse.json({ error: { code: 'CAPTURE_CONFIG_INVALID', message: 'Worker returned invalid page corners.' } }, { status: 502 });
  }

  return NextResponse.json({ corners } satisfies CapturePageResponse, { status: upstream.status });
}
