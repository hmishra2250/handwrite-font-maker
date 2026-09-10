import { NextResponse } from 'next/server';
import { ERROR_COPY, isLiveMode, isLocalMode, isValidNormalizedRectangle, workerBaseUrl, type CaptureForegroundRequest, type CaptureForegroundResponse } from '@/lib/contracts';

export async function POST(request: Request) {
  const body = (await request.json().catch(() => null)) as CaptureForegroundRequest | null;
  if (!body?.inputPhoto?.objectKey) {
    return NextResponse.json({ error: { code: 'UPLOAD_OBJECT_MISSING', message: ERROR_COPY.UPLOAD_OBJECT_MISSING } }, { status: 400 });
  }
  if (!isValidNormalizedRectangle(body.rectangle)) {
    return NextResponse.json({ error: { code: 'CAPTURE_CONFIG_INVALID', message: 'foreground extraction requires a normalized [left, top, right, bottom] rectangle.' } }, { status: 400 });
  }

  if (!(isLocalMode() || isLiveMode())) {
    return NextResponse.json(
      { error: { code: 'INTERNAL_ERROR', message: 'Experimental object cutout requires a configured Python worker. It is not a browser-only AI feature.' } },
      { status: 503 },
    );
  }

  const base = workerBaseUrl();
  if (!base) {
    return NextResponse.json({ error: { code: 'INTERNAL_ERROR', message: 'Worker API URL is not configured.' } }, { status: 500 });
  }

  const upstream = await fetch(new URL('/capture/foreground', base), {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify(body),
    cache: 'no-store',
  });
  const payload: unknown = await upstream.json().catch(() => ({ error: { code: 'INTERNAL_ERROR', message: 'Worker returned a non-JSON response.' } }));
  if (!upstream.ok) return NextResponse.json(payload, { status: upstream.status });

  const result = payload as CaptureForegroundResponse;
  if (!result.maskDataUrl?.startsWith('data:image/png;base64,') || result.method !== 'grabcut' || !Number.isFinite(result.width) || !Number.isFinite(result.height)) {
    return NextResponse.json({ error: { code: 'CAPTURE_CONFIG_INVALID', message: 'Worker returned an invalid foreground mask.' } }, { status: 502 });
  }

  return NextResponse.json(result, { status: upstream.status });
}
