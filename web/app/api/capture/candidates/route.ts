import { NextResponse } from 'next/server';
import { readBoundedJson } from '@/lib/read-json';
import { isValidNormalizedRectangle } from '@/lib/contracts';
import type { CaptureCandidatesRequest, CaptureCandidatesResponse } from '@/lib/capture-candidates';
import type { AuthenticatedRequest } from '@/lib/server-auth';
import { applyAuthCookies, authenticatedWorkerHeaders, enforceMutationOrigin, protectedWorkerBaseUrl, requireAuthenticatedRequest, sanitizeProtectedWorkerError } from '@/lib/server-auth';

const MAX_CANDIDATES = 6;
const MAX_SVG_BYTES = 2_000_000;
const MAX_MASK_BYTES = 2_000_000;
const MAX_CANDIDATE_SIDE = 2048;

function decodeBase64DataUrl(dataUrl: unknown, prefix: string, maxBytes: number): Buffer | null {
  if (typeof dataUrl !== 'string' || !dataUrl.startsWith(prefix)) return null;
  const encoded = dataUrl.slice(prefix.length);
  if (!encoded || encoded.length > Math.ceil(maxBytes / 3) * 4 + 4 || !/^[A-Za-z0-9+/]+={0,2}$/.test(encoded) || encoded.length % 4 === 1) return null;
  try {
    const decoded = Buffer.from(encoded, 'base64');
    if (decoded.length === 0 || decoded.length > maxBytes) return null;
    return decoded;
  } catch {
    return null;
  }
}

function isSafePotraceSvg(svgDataUrl: unknown) {
  const bytes = decodeBase64DataUrl(svgDataUrl, 'data:image/svg+xml;base64,', MAX_SVG_BYTES);
  if (!bytes) return false;
  let svg: string;
  try {
    svg = new TextDecoder('utf-8', { fatal: true }).decode(bytes);
  } catch {
    return false;
  }
  if (!/<\s*svg\b/i.test(svg) || !/<\s*path\b/i.test(svg)) return false;
  if (/<\s*(?:image|script|style|foreignObject|iframe|object|embed|audio|video|canvas|use)\b/i.test(svg)) return false;
  if (/<!ENTITY\b/i.test(svg) || /\son[a-z]+\s*=/i.test(svg) || /\b(?:href|xlink:href)\s*=/i.test(svg) || /url\s*\(/i.test(svg)) return false;
  const allowedTags = new Set(['svg', 'g', 'path', 'metadata']);
  for (const match of svg.matchAll(/<\s*\/?\s*([A-Za-z][A-Za-z0-9:._-]*)\b/g)) {
    if (!allowedTags.has(match[1].toLowerCase())) return false;
  }
  return true;
}

function isValidMask(maskDataUrl: unknown) {
  const bytes = decodeBase64DataUrl(maskDataUrl, 'data:image/png;base64,', MAX_MASK_BYTES);
  return Boolean(bytes?.subarray(0, 8).equals(Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a])));
}

function isTimeoutError(error: unknown) {
  return error instanceof DOMException && (error.name === 'TimeoutError' || error.name === 'AbortError');
}

function workerErrorResponse(auth: AuthenticatedRequest, payload: unknown) {
  if (payload && typeof payload === 'object') return sanitizeProtectedWorkerError(auth, payload, 'Could not prepare letter options.');
  return { error: { code: 'CAPTURE_UPSTREAM_INVALID', message: 'Letter extraction returned an invalid error response.' } };
}

function sanitizeCandidateResponse(payload: unknown, stage: CaptureCandidatesRequest['stage']): CaptureCandidatesResponse | null {
  const result = payload as CaptureCandidatesResponse | null;
  if (!result || !Array.isArray(result.candidates) || result.candidates.length > MAX_CANDIDATES || !Array.isArray(result.failures) || result.stage !== stage) return null;
  if (result.failures.some(failure => typeof failure?.method !== 'string' || typeof failure?.message !== 'string' || failure.method.length > 64 || failure.message.length > 512)) return null;
  const candidates = result.candidates.map((candidate) => {
    if (typeof candidate?.id !== 'string' || candidate.id.length > 128 ||
        typeof candidate.label !== 'string' || candidate.label.length > 128 ||
        !isValidMask(candidate.maskDataUrl) || !isSafePotraceSvg(candidate.svgDataUrl) ||
        !Number.isFinite(candidate.width) || candidate.width <= 0 || candidate.width > MAX_CANDIDATE_SIDE ||
        !Number.isFinite(candidate.height) || candidate.height <= 0 || candidate.height > MAX_CANDIDATE_SIDE ||
        typeof candidate.method !== 'string' || candidate.method.length > 128 ||
        (candidate.polarity != null && typeof candidate.polarity !== 'string') ||
        !Array.isArray(candidate.warnings) || candidate.warnings.some(warning => typeof warning !== 'string' || warning.length > 512)) {
      return null;
    }
    return {
      id: candidate.id,
      label: candidate.label,
      maskDataUrl: candidate.maskDataUrl,
      svgDataUrl: candidate.svgDataUrl,
      width: candidate.width,
      height: candidate.height,
      method: candidate.method,
      ...(candidate.polarity ? { polarity: candidate.polarity } : {}),
      warnings: candidate.warnings,
    };
  });
  if (candidates.some(candidate => candidate === null)) return null;
  return { candidates: candidates as CaptureCandidatesResponse['candidates'], failures: result.failures, stage: result.stage };
}

export async function POST(request: Request) {
  const originError = enforceMutationOrigin(request);
  if (originError) return originError;
  const access = await requireAuthenticatedRequest(request);
  if (!access.ok) return access.response;
  const auth = access.auth;
  const json = (body: unknown, status: number) => applyAuthCookies(NextResponse.json(body, { status }), auth);
  const body = await readBoundedJson(request, 8192) as CaptureCandidatesRequest | null;
  if (!body?.inputPhoto?.objectKey || !isValidNormalizedRectangle(body.rectangle) || !['ink','objects'].includes(body.stage)) {
    return json({ error: { code: 'CAPTURE_CONFIG_INVALID', message: 'Choose a photo and a valid letter selection.' } }, 400);
  }
  const base = protectedWorkerBaseUrl(auth);
  if (!base) return json({ error: { code: 'INTERNAL_ERROR', message: 'Letter extraction is not configured.' } }, 503);
  try {
    const upstream = await fetch(new URL('/capture/candidates', base), {
      method: 'POST', headers: authenticatedWorkerHeaders(auth, { 'content-type': 'application/json' }),
      body: JSON.stringify(body), cache: 'no-store', signal: AbortSignal.timeout(40_000),
    });
    const payload = await upstream.json().catch(() => null);
    if (!upstream.ok) return json(workerErrorResponse(auth, payload), upstream.status);
    const result = sanitizeCandidateResponse(payload, body.stage);
    if (!result) {
      return json({ error: { code: 'CAPTURE_CONFIG_INVALID', message: 'Extraction returned invalid letter options.' } }, 502);
    }
    return json(result, 200);
  } catch (error) {
    if (isTimeoutError(error)) return json({ error: { code: 'CAPTURE_TIMEOUT', message: 'These options took too long. Keep an existing option or retry.' } }, 504);
    return json({ error: { code: 'CAPTURE_UPSTREAM_UNAVAILABLE', message: 'Letter extraction is temporarily unavailable. Keep an existing option or retry.' } }, 502);
  }
}
