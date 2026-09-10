import { NextResponse } from 'next/server';
import { ERROR_COPY, isLiveMode, isLocalMode, MAX_UPLOAD_BYTES, workerBaseUrl } from '@/lib/contracts';

type Params = { params: Promise<{ key: string[] }> };

function objectPath(parts: string[]) {
  return parts.map((part) => encodeURIComponent(part)).join('/');
}

async function readBoundedUploadBlob(request: Request, maxBytes: number): Promise<Blob | 'too_large'> {
  const contentType = request.headers.get('content-type') ?? 'image/png';
  if (!request.body) return new Blob([], { type: contentType });
  const reader = request.body.getReader();
  const chunks: ArrayBuffer[] = [];
  let total = 0;
  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      total += value.byteLength;
      if (total > maxBytes) {
        await reader.cancel().catch(() => undefined);
        return 'too_large';
      }
      chunks.push(value.buffer.slice(value.byteOffset, value.byteOffset + value.byteLength) as ArrayBuffer);
    }
  } finally {
    reader.releaseLock();
  }
  return new Blob(chunks, { type: contentType });
}

async function proxyObject(request: Request, { params }: Params, method: 'GET' | 'PUT') {
  if (!(isLocalMode() || isLiveMode())) {
    return NextResponse.json({ error: { code: 'INTERNAL_ERROR', message: 'Object proxy requires a configured Python worker.' } }, { status: 503 });
  }
  const { key } = await params;
  const base = workerBaseUrl();
  if (!base || !key?.length) {
    return NextResponse.json({ error: { code: 'UPLOAD_OBJECT_MISSING', message: 'Object key is required.' } }, { status: 400 });
  }

  let uploadBody: Blob | undefined;
  if (method === 'PUT') {
    const sizeHeader = Number(request.headers.get('content-length') ?? 0);
    if (sizeHeader > MAX_UPLOAD_BYTES) {
      return NextResponse.json({ error: { code: 'UPLOAD_OBJECT_TOO_LARGE', message: ERROR_COPY.UPLOAD_OBJECT_TOO_LARGE } }, { status: 413 });
    }
    const boundedBody = await readBoundedUploadBlob(request, MAX_UPLOAD_BYTES);
    if (boundedBody === 'too_large') {
      return NextResponse.json({ error: { code: 'UPLOAD_OBJECT_TOO_LARGE', message: ERROR_COPY.UPLOAD_OBJECT_TOO_LARGE } }, { status: 413 });
    }
    uploadBody = boundedBody;
  }

  const upstream = await fetch(new URL(`/objects/${objectPath(key)}`, base), {
    method,
    headers: method === 'PUT' ? { 'content-type': request.headers.get('content-type') ?? 'image/png' } : undefined,
    body: uploadBody,
    cache: 'no-store',
  });

  if (method === 'PUT') {
    if (!upstream.ok) {
      const payload = await upstream.json().catch(() => ({ error: { code: 'INTERNAL_ERROR', message: 'Worker object upload failed.' } }));
      return NextResponse.json(payload, { status: upstream.status });
    }
    return new Response(null, { status: upstream.status });
  }

  return new Response(upstream.body, {
    status: upstream.status,
    headers: {
      'content-type': upstream.headers.get('content-type') ?? 'application/octet-stream',
      'cache-control': 'no-store',
    },
  });
}

export async function PUT(request: Request, context: Params) {
  return proxyObject(request, context, 'PUT');
}

export async function GET(request: Request, context: Params) {
  return proxyObject(request, context, 'GET');
}
