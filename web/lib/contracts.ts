export const MAX_UPLOAD_BYTES = Number(process.env.NEXT_PUBLIC_MAX_UPLOAD_BYTES ?? process.env.MAX_UPLOAD_BYTES ?? 15 * 1024 * 1024);
export const JOB_RETENTION_HOURS = Number(process.env.NEXT_PUBLIC_JOB_RETENTION_HOURS ?? process.env.JOB_RETENTION_HOURS ?? 24);

export const HARD_ERROR_CODES = [
  'MARKER_NOT_FOUND',
  'MARKER_AMBIGUOUS',
  'MARKER_GEOMETRY_INVALID',
  'TEMPLATE_BORDER_CROPPED',
  'HOMOGRAPHY_FAILED',
  'HOMOGRAPHY_CONFIDENCE_LOW',
  'RECTIFIED_PAGE_OUT_OF_BOUNDS',
  'GLYPH_GRID_NOT_FOUND',
  'GLYPH_EXTRACTION_FAILED',
  'GLYPH_REQUIRED_SET_MISSING',
  'FONTFORGE_UNAVAILABLE',
  'POTRACE_UNAVAILABLE',
  'FONT_GENERATION_FAILED',
  'FONT_VALIDATION_FAILED',
  'FONT_METADATA_INVALID',
  'UPLOAD_OBJECT_MISSING',
  'UPLOAD_OBJECT_TOO_LARGE',
  'UNSUPPORTED_IMAGE_TYPE',
  'CAPTURE_CONFIG_INVALID',
  'ARTIFACT_PUBLISH_FAILED',
  'JOB_EXPIRED',
  'INTERNAL_ERROR'
] as const;

export type HardErrorCode = (typeof HARD_ERROR_CODES)[number];

export const JOB_STATUSES = ['idle', 'preparing_upload', 'uploading', 'creating_job', 'queued', 'running', 'succeeded', 'failed', 'expired'] as const;
export type JobStatus = (typeof JOB_STATUSES)[number];

export const JOB_STAGES = [
  'upload_received',
  'queued',
  'marker_detection',
  'homography_rectification',
  'glyph_extraction',
  'font_generation',
  'font_validation',
  'artifact_publish',
  'complete'
] as const;
export type JobStage = (typeof JOB_STAGES)[number];

export type ArtifactKind = 'otf' | 'ttf' | 'sfd' | 'debug_overlay' | 'rectified_page' | 'manifest' | 'log_excerpt' | 'zip_bundle';

export interface InputPhotoRef {
  bucket?: string;
  objectKey: string;
  contentType: string;
  sizeBytes: number;
  sha256?: string;
}

export interface FontMetadata {
  fontName: string;
  familyName: string;
  styleName: string;
}

export type NormalizedPoint = readonly [number, number];
export type PageCorners = readonly [NormalizedPoint, NormalizedPoint, NormalizedPoint, NormalizedPoint];

export interface TemplateCaptureConfig {
  mode: 'template';
  templateId: 'default-v1';
  paperSize: 'A4';
  alignment: 'markers' | 'page';
  corners?: PageCorners;
}

export interface GuidedGlyphInput {
  char: string;
  inputPhoto: InputPhotoRef;
  baseline: number;
}

export interface GuidedCaptureConfig {
  mode: 'guided';
  format: 'mask-v1';
  glyphs: GuidedGlyphInput[];
}

export type CaptureConfig = TemplateCaptureConfig | GuidedCaptureConfig;

export interface CreateJobRequest {
  inputPhoto: InputPhotoRef;
  font: FontMetadata;
  template: {
    version: 'v1';
    templateId?: string;
  };
  capture?: CaptureConfig;
}

export interface CapturePageRequest {
  inputPhoto: InputPhotoRef;
}

export type NormalizedRectangle = readonly [number, number, number, number];

export interface CaptureForegroundRequest {
  inputPhoto: InputPhotoRef;
  rectangle: NormalizedRectangle;
}

export interface CaptureForegroundResponse {
  maskDataUrl: string;
  width: number;
  height: number;
  method: 'grabcut';
}

export interface CapturePageResponse {
  corners: PageCorners;
}

export interface UploadRequest {
  filename: string;
  contentType: string;
  sizeBytes: number;
}

export interface UploadResponse {
  mode: 'live' | 'local' | 'demo';
  uploadUrl: string;
  method: 'PUT' | 'POST';
  objectKey: string;
  bucket?: string;
  expiresAt: string;
  maxUploadBytes: number;
}

export interface JobWarning {
  code: string;
  glyph?: string;
  message: string;
  severity: 'warning';
  details?: Record<string, unknown>;
}

export interface JobArtifact {
  kind: ArtifactKind;
  label: string;
  objectKey: string;
  url?: string;
  contentType: string;
  sizeBytes: number;
  expiresAt?: string;
}

export interface JobError {
  code: HardErrorCode;
  message: string;
  retryable: boolean;
  details?: Record<string, unknown>;
}

export interface JobResponse {
  jobId: string;
  status: Extract<JobStatus, 'queued' | 'running' | 'succeeded' | 'failed' | 'expired'>;
  stage: JobStage | 'complete';
  progressLabel?: string;
  warnings: JobWarning[];
  artifacts: JobArtifact[];
  error?: JobError;
  retentionExpiresAt: string;
}

export const ERROR_COPY: Record<HardErrorCode, string> = {
  MARKER_NOT_FOUND: 'We could not find all four page markers. Retake the photo with the entire page visible.',
  MARKER_AMBIGUOUS: 'The page markers were detected inconsistently. Retake the photo on a flatter surface.',
  MARKER_GEOMETRY_INVALID: 'The page or corner geometry does not match the template. Retake the photo straight-on or correct the corners.',
  TEMPLATE_BORDER_CROPPED: 'The template border appears cropped. Retake with margin around the full page.',
  HOMOGRAPHY_FAILED: 'Perspective correction failed. Retake with less tilt and all corners visible.',
  HOMOGRAPHY_CONFIDENCE_LOW: 'The page was detected, but the warp looked unreliable. Retake with the sheet flatter.',
  RECTIFIED_PAGE_OUT_OF_BOUNDS: 'The rectified page fell outside expected bounds. Retake from farther away.',
  GLYPH_GRID_NOT_FOUND: 'The glyph cell layout could not be extracted from the template.',
  GLYPH_EXTRACTION_FAILED: 'Glyph extraction failed before font generation.',
  GLYPH_REQUIRED_SET_MISSING: 'The template did not contain the required character set.',
  FONTFORGE_UNAVAILABLE: 'The backend font builder is missing FontForge. This is a server configuration issue.',
  POTRACE_UNAVAILABLE: 'The backend font builder is missing potrace. This is a server configuration issue.',
  FONT_GENERATION_FAILED: 'Font generation failed after glyph extraction.',
  FONT_VALIDATION_FAILED: 'The generated font failed validation. Retake the photo or try a simpler font name.',
  FONT_METADATA_INVALID: 'The font metadata is invalid. Use letters, numbers, spaces, hyphens, or underscores.',
  UPLOAD_OBJECT_MISSING: 'The uploaded source photo was not found. Upload the photo again.',
  UPLOAD_OBJECT_TOO_LARGE: 'The photo is larger than the configured upload limit.',
  UNSUPPORTED_IMAGE_TYPE: 'Upload a JPEG, PNG, or WebP image.',
  CAPTURE_CONFIG_INVALID: 'The capture configuration is invalid. Review the selected mode and accepted glyphs or corners.',
  ARTIFACT_PUBLISH_FAILED: 'The font built, but artifact upload failed. Try again later.',
  JOB_EXPIRED: 'This job expired and its files are no longer available.',
  INTERNAL_ERROR: 'An unexpected backend error occurred. Try again with a fresh upload.'
};

export function isLiveMode() {
  return Boolean(process.env.WORKER_API_BASE_URL && process.env.SUPABASE_URL && process.env.SUPABASE_SERVICE_ROLE_KEY && process.env.SUPABASE_STORAGE_BUCKET);
}

/** Local mode: Python backend is reachable but Supabase is not configured. */
export function isLocalMode() {
  return Boolean(process.env.WORKER_API_BASE_URL) && !isLiveMode();
}

export function workerBaseUrl() {
  return process.env.WORKER_API_BASE_URL ?? '';
}

export function retentionExpiry(hours = JOB_RETENTION_HOURS) {
  return new Date(Date.now() + hours * 60 * 60 * 1000).toISOString();
}

export function isSupportedImage(contentType: string) {
  return ['image/jpeg', 'image/png', 'image/webp'].includes(contentType);
}

export function isSafeFontName(fontName: string) {
  return /^[A-Za-z0-9][A-Za-z0-9_-]{1,62}$/.test(fontName);
}

export function isPrintableNonSpaceAscii(char: string) {
  if (char.length !== 1) return false;
  const code = char.charCodeAt(0);
  return code >= 33 && code <= 126;
}

export function isValidBaseline(value: number) {
  return Number.isFinite(value) && value > 0 && value < 1;
}

export function isValidNormalizedRectangle(rectangle: unknown): rectangle is NormalizedRectangle {
  if (!Array.isArray(rectangle) || rectangle.length !== 4) return false;
  const [left, top, right, bottom] = rectangle;
  return [left, top, right, bottom].every((value) => Number.isFinite(value) && value >= 0 && value <= 1) && left < right && top < bottom;
}

export function isValidPageCorners(corners: unknown): corners is PageCorners {
  if (!Array.isArray(corners) || corners.length !== 4) return false;
  const seen = new Set<string>();
  for (const point of corners) {
    if (!Array.isArray(point) || point.length !== 2) return false;
    const [x, y] = point;
    if (!Number.isFinite(x) || !Number.isFinite(y) || x < 0 || x > 1 || y < 0 || y > 1) return false;
    const key = `${Math.round(x * 10000)}:${Math.round(y * 10000)}`;
    if (seen.has(key)) return false;
    seen.add(key);
  }
  return true;
}

export function validateCaptureConfig(capture: unknown): string | null {
  if (capture === undefined) return null;
  if (!capture || typeof capture !== 'object') return 'capture must be an object.';
  const value = capture as Record<string, unknown>;
  if (value.mode === 'template') {
    if (value.templateId !== 'default-v1') return 'template capture requires templateId default-v1.';
    if (value.paperSize !== 'A4') return 'template capture requires paperSize A4.';
    if (value.alignment !== 'markers' && value.alignment !== 'page') return 'template capture requires markers or page alignment.';
    if (value.alignment === 'page' && !isValidPageCorners(value.corners)) return 'page alignment requires four confirmed normalized corners.';
    return null;
  }
  if (value.mode === 'guided') {
    if (value.format !== 'mask-v1') return 'guided capture requires mask-v1 format.';
    if (!Array.isArray(value.glyphs) || value.glyphs.length < 1 || value.glyphs.length > 94) return 'guided capture requires 1 to 94 glyphs.';
    const seen = new Set<string>();
    for (const glyph of value.glyphs) {
      if (!glyph || typeof glyph !== 'object') return 'each guided glyph must be an object.';
      const g = glyph as Record<string, unknown>;
      if (typeof g.char !== 'string' || !isPrintableNonSpaceAscii(g.char)) return 'guided glyph labels must be printable non-space ASCII.';
      if (seen.has(g.char)) return 'guided glyph labels must be unique.';
      seen.add(g.char);
      if (!g.inputPhoto || typeof g.inputPhoto !== 'object' || !(g.inputPhoto as InputPhotoRef).objectKey) return 'each guided glyph requires an uploaded mask image.';
      if (!isValidBaseline(Number(g.baseline))) return 'each guided glyph baseline must be between 0 and 1.';
    }
    return null;
  }
  return 'unknown capture mode.';
}
