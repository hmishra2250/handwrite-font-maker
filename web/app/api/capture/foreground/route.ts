import { readBoundedJson } from '@/lib/read-json';
import { NextResponse } from 'next/server';
import {
  ERROR_COPY,
  isLiveMode,
  isLocalMode,
  isValidCaptureForegroundMethod,
  isValidCaptureForegroundPromptPoints,
  isValidCaptureForegroundStyle,
  isValidCaptureForegroundThreshold,
  isValidNormalizedRectangle,
  type CaptureForegroundRequest,
  type CaptureForegroundResponse,
} from '@/lib/contracts';
import { applyAuthCookies, authenticatedWorkerHeaders, enforceMutationOrigin, protectedWorkerBaseUrl, requireAuthenticatedRequest, sanitizeProtectedWorkerError } from '@/lib/server-auth';

export async function POST(request: Request) {
  const originError = enforceMutationOrigin(request);
  if (originError) return originError;
  const authResult = await requireAuthenticatedRequest(request);
  if (!authResult.ok) return authResult.response;
  const auth = authResult.auth;
  const json = (body: unknown, init?: ResponseInit) => applyAuthCookies(NextResponse.json(body, init), auth);
  const body = (await readBoundedJson(request)) as CaptureForegroundRequest | null;
  if (!body?.inputPhoto?.objectKey) {
    return json({ error: { code: 'UPLOAD_OBJECT_MISSING', message: ERROR_COPY.UPLOAD_OBJECT_MISSING } }, { status: 400 });
  }
  if (!isValidNormalizedRectangle(body.rectangle)) {
    return json({ error: { code: 'CAPTURE_CONFIG_INVALID', message: 'foreground extraction requires a normalized [left, top, right, bottom] rectangle.' } }, { status: 400 });
  }
  const method = body.method ?? 'auto';
  if (!isValidCaptureForegroundMethod(method)) {
    return json({ error: { code: 'CAPTURE_CONFIG_INVALID', message: 'foreground extraction method must be auto, model, box-model, or grabcut.' } }, { status: 400 });
  }
  const style = body.style ?? 'silhouette';
  if (!isValidCaptureForegroundStyle(style)) {
    return json({ error: { code: 'CAPTURE_CONFIG_INVALID', message: 'foreground extraction style must be silhouette or ink.' } }, { status: 400 });
  }
  const threshold = body.threshold ?? (style === 'ink' ? 128 : undefined);
  if (threshold !== undefined && !isValidCaptureForegroundThreshold(threshold)) {
    return json({ error: { code: 'CAPTURE_CONFIG_INVALID', message: 'foreground extraction threshold must be an integer from 1 to 254.' } }, { status: 400 });
  }
  if (!isValidCaptureForegroundPromptPoints(body.points)) {
    return json({ error: { code: 'CAPTURE_CONFIG_INVALID', message: 'foreground extraction points must be up to 16 normalized {x, y, label} prompts.' } }, { status: 400 });
  }
  if (method === 'box-model' && body.points && body.points.length > 0) {
    return json({ error: { code: 'CAPTURE_CONFIG_INVALID', message: 'EfficientSAM box cutout uses only the rectangle prompt; remove point prompts before requesting box-model.' } }, { status: 400 });
  }
  if (method === 'model' && !body.points?.some((point) => point.label === 1)) {
    return json({ error: { code: 'CAPTURE_CONFIG_INVALID', message: 'model foreground extraction requires at least one Keep object point.' } }, { status: 400 });
  }

  if (!(auth.protected || isLocalMode() || isLiveMode())) {
    if (method === 'model' || method === 'box-model') {
      return json(
        { error: { code: 'INTERNAL_ERROR', message: 'Model foreground extraction requires a configured Python worker with a segmentation model. No browser-only AI fallback is available.' } },
        { status: 503 },
      );
    }
    return json(
      { error: { code: 'INTERNAL_ERROR', message: 'Experimental object cutout requires a configured Python worker. It is not a browser-only AI feature.' } },
      { status: 503 },
    );
  }

  const base = protectedWorkerBaseUrl(auth);
  if (!base) {
    return json({ error: { code: 'INTERNAL_ERROR', message: 'Worker API URL is not configured.' } }, { status: 500 });
  }

  const upstream = await fetch(new URL('/capture/foreground', base), {
    method: 'POST',
    headers: authenticatedWorkerHeaders(auth, { 'content-type': 'application/json' }),
    body: JSON.stringify({
      inputPhoto: body.inputPhoto,
      rectangle: body.rectangle,
      method,
      style,
      ...(threshold === undefined ? {} : { threshold }),
      ...(method === 'auto' || method === 'model' ? (body.points === undefined ? {} : { points: body.points }) : {}),
    } satisfies CaptureForegroundRequest),
    cache: 'no-store',
  });
  const payload: unknown = await upstream.json().catch(() => ({ error: { code: 'INTERNAL_ERROR', message: 'Worker returned a non-JSON response.' } }));
  if (!upstream.ok) return applyAuthCookies(NextResponse.json(sanitizeProtectedWorkerError(auth, payload, 'Foreground extraction failed.'), { status: upstream.status }), auth);

  const result = payload as CaptureForegroundResponse;
  const validMethod = result.method === 'grabcut' || result.method === 'slimsam' || result.method === 'efficientsam';
  const validWarnings = result.warnings === undefined || (Array.isArray(result.warnings) && result.warnings.every((warning) => typeof warning === 'string'));
  const modelId = (payload as { modelId?: unknown }).modelId;
  const validModelId = modelId === undefined || modelId === null || typeof modelId === 'string';
  if (
    !result.maskDataUrl?.startsWith('data:image/png;base64,') ||
    !validMethod ||
    (method === 'model' && result.method !== 'slimsam') ||
    (method === 'box-model' && result.method !== 'efficientsam') ||
    !Number.isFinite(result.width) ||
    !Number.isFinite(result.height) ||
    result.width <= 0 ||
    result.height <= 0 ||
    !validWarnings ||
    !validModelId
  ) {
    return json({ error: { code: 'CAPTURE_CONFIG_INVALID', message: 'Worker returned an invalid foreground mask.' } }, { status: 502 });
  }

  return applyAuthCookies(NextResponse.json({
    maskDataUrl: result.maskDataUrl,
    width: result.width,
    height: result.height,
    method: result.method,
    ...(typeof modelId === 'string' ? { modelId } : {}),
    ...(result.warnings === undefined ? {} : { warnings: result.warnings }),
  } satisfies CaptureForegroundResponse, { status: upstream.status }), auth);
}
