export const MAX_UPLOAD_BYTES = Number(process.env.NEXT_PUBLIC_MAX_UPLOAD_BYTES ?? process.env.MAX_UPLOAD_BYTES ?? 15 * 1024 * 1024);
export const JOB_RETENTION_HOURS = Number(process.env.NEXT_PUBLIC_JOB_RETENTION_HOURS ?? process.env.JOB_RETENTION_HOURS ?? 24);

export const HARD_ERROR_CODES = [
  'MARKER_NOT_FOUND',
  'MARKER_AMBIGUOUS',
  'MARKER_GEOMETRY_INVALID',
  'TEMPLATE_BORDER_CROPPED',
  'QR_NOT_FOUND',
  'QR_UNREADABLE',
  'QR_TEMPLATE_VERSION_UNSUPPORTED',
  'QR_TEMPLATE_MISMATCH',
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
  'qr_decode',
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

export interface CreateJobRequest {
  inputPhoto: InputPhotoRef;
  font: FontMetadata;
  template: {
    version: 'v1';
    templateId?: string;
  };
}

export interface UploadRequest {
  filename: string;
  contentType: string;
  sizeBytes: number;
}

export interface UploadResponse {
  mode: 'live' | 'demo';
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
  MARKER_GEOMETRY_INVALID: 'The marker geometry does not match the template. Retake the photo straight-on.',
  TEMPLATE_BORDER_CROPPED: 'The template border appears cropped. Retake with margin around the full page.',
  QR_NOT_FOUND: 'The template QR code was not found. Use the V1 template and keep the top area visible.',
  QR_UNREADABLE: 'The QR code could not be read. Retake the photo with sharper focus and less glare.',
  QR_TEMPLATE_VERSION_UNSUPPORTED: 'This template version is not supported by the current builder.',
  QR_TEMPLATE_MISMATCH: 'The QR metadata does not match the expected V1 layout.',
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
  ARTIFACT_PUBLISH_FAILED: 'The font built, but artifact upload failed. Try again later.',
  JOB_EXPIRED: 'This job expired and its files are no longer available.',
  INTERNAL_ERROR: 'An unexpected backend error occurred. Try again with a fresh upload.'
};

export function isLiveMode() {
  return Boolean(process.env.WORKER_API_BASE_URL && process.env.SUPABASE_URL && process.env.SUPABASE_SERVICE_ROLE_KEY && process.env.SUPABASE_STORAGE_BUCKET);
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
