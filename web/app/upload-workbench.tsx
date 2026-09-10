'use client';

import { FormEvent, KeyboardEvent, MouseEvent, type RefObject, useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  ERROR_COPY,
  isSafeFontName,
  isSupportedImage,
  MAX_UPLOAD_BYTES,
  type CaptureForegroundResponse,
  type CapturePageResponse,
  type CreateJobRequest,
  type InputPhotoRef,
  type JobResponse,
  type JobStage,
  type NormalizedRectangle,
  type PageCorners,
  type UploadResponse,
} from '@/lib/contracts';

type LocalState =
  | 'idle'
  | 'preparing_upload'
  | 'uploading'
  | 'creating_job'
  | 'polling'
  | 'succeeded'
  | 'failed';

type WorkbenchMode = 'guided' | 'markerless' | 'legacy';
type GuidedMaskMethod = 'threshold' | 'object';
type CornerIndex = 0 | 1 | 2 | 3;

type MaskResult = {
  blob: Blob;
  width: number;
  height: number;
  foregroundRatio: number;
};

type CurrentMask = MaskResult & { url: string };

type AcceptedGlyph = {
  char: string;
  blob: Blob;
  url: string;
  baseline: number;
  width: number;
  height: number;
  foregroundRatio: number;
  filename: string;
};

const POLL_INTERVAL_MS = 2000;
const MAX_POLLS = 120;
const MASK_MAX_SIDE = 1024;
const GUIDED_CHARACTER_ORDER = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789' + Array.from({ length: 94 }, (_, i) => String.fromCharCode(i + 33)).filter((char) => !/[A-Za-z0-9]/.test(char)).join('');
const GUIDED_CHARACTERS = Array.from(GUIDED_CHARACTER_ORDER);
const DEFAULT_CORNERS: PageCorners = [[0.08, 0.08], [0.92, 0.08], [0.92, 0.92], [0.08, 0.92]];
const DEFAULT_FOREGROUND_RECTANGLE: NormalizedRectangle = [0.12, 0.12, 0.88, 0.88];
const CORNER_LABELS = ['TL', 'TR', 'BR', 'BL'] as const;

const PIPELINE_STAGES: { key: JobStage; label: string }[] = [
  { key: 'marker_detection', label: 'Finding page / markers' },
  { key: 'homography_rectification', label: 'Correcting perspective' },
  { key: 'glyph_extraction', label: 'Extracting glyph masks' },
  { key: 'font_generation', label: 'Generating font outlines' },
  { key: 'font_validation', label: 'Validating font files' },
  { key: 'artifact_publish', label: 'Publishing downloads' },
];

function stageIndex(stage: string): number {
  return PIPELINE_STAGES.findIndex((s) => s.key === stage);
}

function uploadRefFromSlot(slot: UploadResponse, contentType: string, sizeBytes: number): InputPhotoRef {
  return { objectKey: slot.objectKey, bucket: slot.bucket, contentType, sizeBytes };
}

function clamp01(value: number) {
  if (!Number.isFinite(value)) return 0;
  return Math.min(1, Math.max(0, value));
}

type RectLike = { left: number; top: number; width: number; height: number };

export function containedImageBounds(imageRect: RectLike, naturalWidth: number, naturalHeight: number): RectLike {
  if (imageRect.width <= 0 || imageRect.height <= 0 || naturalWidth <= 0 || naturalHeight <= 0) return imageRect;
  const scale = Math.min(imageRect.width / naturalWidth, imageRect.height / naturalHeight);
  const width = naturalWidth * scale;
  const height = naturalHeight * scale;
  return {
    left: imageRect.left + (imageRect.width - width) / 2,
    top: imageRect.top + (imageRect.height - height) / 2,
    width,
    height,
  };
}

export function normalizedPointInContainedImage(clientX: number, clientY: number, imageRect: RectLike, naturalWidth: number, naturalHeight: number): [number, number] {
  const bounds = containedImageBounds(imageRect, naturalWidth, naturalHeight);
  return [clamp01((clientX - bounds.left) / bounds.width), clamp01((clientY - bounds.top) / bounds.height)];
}

function updateCorner(corners: PageCorners, index: CornerIndex, x: number, y: number): PageCorners {
  const point: [number, number] = [clamp01(x), clamp01(y)];
  return [
    index === 0 ? point : corners[0],
    index === 1 ? point : corners[1],
    index === 2 ? point : corners[2],
    index === 3 ? point : corners[3],
  ];
}

function glyphFilename(char: string) {
  return `glyph-u${char.charCodeAt(0).toString(16).padStart(4, '0')}.png`;
}

function CameraIcon({ className }: { className?: string }) {
  return (
    <svg className={className} width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
      <path d="M23 19a2 2 0 0 1-2 2H3a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h4l2-3h6l2 3h4a2 2 0 0 1 2 2z" />
      <circle cx="12" cy="13" r="4" />
    </svg>
  );
}

function UploadIcon({ className }: { className?: string }) {
  return (
    <svg className={className} width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
      <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
      <polyline points="17 8 12 3 7 8" />
      <line x1="12" y1="3" x2="12" y2="15" />
    </svg>
  );
}

function XIcon() {
  return (
    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <line x1="18" y1="6" x2="6" y2="18" />
      <line x1="6" y1="6" x2="18" y2="18" />
    </svg>
  );
}

function CheckIcon() {
  return (
    <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round">
      <polyline points="20 6 9 17 4 12" />
    </svg>
  );
}

async function loadImage(file: Blob): Promise<HTMLImageElement> {
  const url = URL.createObjectURL(file);
  try {
    const image = new Image();
    image.decoding = 'async';
    image.src = url;
    await new Promise<void>((resolve, reject) => {
      image.onload = () => resolve();
      image.onerror = () => reject(new Error('Could not decode this image. Try a JPEG, PNG, or WebP export.'));
    });
    return image;
  } finally {
    URL.revokeObjectURL(url);
  }
}

export async function createMaskPngFromFile(file: Blob, threshold: number, invert: boolean): Promise<MaskResult> {
  const image = await loadImage(file);
  const sourceWidth = image.naturalWidth || image.width;
  const sourceHeight = image.naturalHeight || image.height;
  if (!sourceWidth || !sourceHeight) throw new Error('Could not read image dimensions.');

  const scale = Math.min(1, MASK_MAX_SIDE / Math.max(sourceWidth, sourceHeight));
  const width = Math.max(1, Math.round(sourceWidth * scale));
  const height = Math.max(1, Math.round(sourceHeight * scale));
  const canvas = document.createElement('canvas');
  canvas.width = width;
  canvas.height = height;
  const ctx = canvas.getContext('2d', { willReadFrequently: true });
  if (!ctx) throw new Error('This browser could not prepare the mask canvas.');

  ctx.drawImage(image, 0, 0, width, height);
  const data = ctx.getImageData(0, 0, width, height);
  let foreground = 0;
  for (let i = 0; i < data.data.length; i += 4) {
    const r = data.data[i] ?? 0;
    const g = data.data[i + 1] ?? 0;
    const b = data.data[i + 2] ?? 0;
    const luma = 0.299 * r + 0.587 * g + 0.114 * b;
    const isForeground = invert ? luma > threshold : luma < threshold;
    const value = isForeground ? 0 : 255;
    data.data[i] = value;
    data.data[i + 1] = value;
    data.data[i + 2] = value;
    data.data[i + 3] = 255;
    if (isForeground) foreground++;
  }
  ctx.putImageData(data, 0, 0);

  const blob = await new Promise<Blob>((resolve, reject) => {
    canvas.toBlob((result) => {
      if (result) resolve(result);
      else reject(new Error('Could not encode the accepted mask PNG.'));
    }, 'image/png');
  });

  return { blob, width, height, foregroundRatio: foreground / (width * height) };
}

function dataUrlToBlob(dataUrl: string): Blob {
  const [header, encoded] = dataUrl.split(',');
  if (!header?.startsWith('data:image/png;base64') || !encoded) throw new Error('Worker did not return a PNG mask.');
  const binary = atob(encoded);
  const bytes = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i++) bytes[i] = binary.charCodeAt(i);
  return new Blob([bytes], { type: 'image/png' });
}

async function measureMaskBlob(blob: Blob): Promise<MaskResult> {
  const image = await loadImage(blob);
  const width = image.naturalWidth || image.width;
  const height = image.naturalHeight || image.height;
  const canvas = document.createElement('canvas');
  canvas.width = width;
  canvas.height = height;
  const ctx = canvas.getContext('2d', { willReadFrequently: true });
  if (!ctx) throw new Error('This browser could not inspect the returned mask.');
  ctx.drawImage(image, 0, 0, width, height);
  const data = ctx.getImageData(0, 0, width, height);
  let foreground = 0;
  for (let i = 0; i < data.data.length; i += 4) {
    const r = data.data[i] ?? 255;
    const g = data.data[i + 1] ?? 255;
    const b = data.data[i + 2] ?? 255;
    if ((r + g + b) / 3 < 128) foreground++;
  }
  return { blob, width, height, foregroundRatio: foreground / (width * height) };
}

function normalizeRectangle(rectangle: NormalizedRectangle): NormalizedRectangle {
  const [left, top, right, bottom] = rectangle;
  const l = Math.min(clamp01(left), clamp01(right - 0.01));
  const t = Math.min(clamp01(top), clamp01(bottom - 0.01));
  const r = Math.max(clamp01(right), clamp01(l + 0.01));
  const b = Math.max(clamp01(bottom), clamp01(t + 0.01));
  return [l, t, r, b];
}

export function UploadWorkbench() {
  const [mode, setMode] = useState<WorkbenchMode>('guided');
  const [legacyFile, setLegacyFile] = useState<File | null>(null);
  const [legacyPreview, setLegacyPreview] = useState<string | null>(null);
  const [pageFile, setPageFile] = useState<File | null>(null);
  const [pagePreview, setPagePreview] = useState<string | null>(null);
  const [pageUploadRef, setPageUploadRef] = useState<InputPhotoRef | null>(null);
  const [corners, setCorners] = useState<PageCorners>(DEFAULT_CORNERS);
  const [selectedCorner, setSelectedCorner] = useState<CornerIndex>(0);
  const [cornersConfirmed, setCornersConfirmed] = useState(false);
  const [cornerStatus, setCornerStatus] = useState<string | null>(null);
  const [guidedFile, setGuidedFile] = useState<File | null>(null);
  const [guidedPreview, setGuidedPreview] = useState<string | null>(null);
  const [guidedUploadRef, setGuidedUploadRef] = useState<InputPhotoRef | null>(null);
  const [guidedMaskMethod, setGuidedMaskMethod] = useState<GuidedMaskMethod>('threshold');
  const [foregroundRectangle, setForegroundRectangle] = useState<NormalizedRectangle>(DEFAULT_FOREGROUND_RECTANGLE);
  const [foregroundStatus, setForegroundStatus] = useState<string | null>(null);
  const [threshold, setThreshold] = useState(170);
  const [invert, setInvert] = useState(false);
  const [baseline, setBaseline] = useState(0.8);
  const [currentCharIndex, setCurrentCharIndex] = useState(0);
  const [currentMask, setCurrentMask] = useState<CurrentMask | null>(null);
  const [acceptedGlyphs, setAcceptedGlyphs] = useState<Record<string, AcceptedGlyph>>({});
  const [fontName, setFontName] = useState('MyHandwrite-Regular');
  const [familyName, setFamilyName] = useState('My Handwrite');
  const [styleName, setStyleName] = useState('Regular');
  const [state, setState] = useState<LocalState>('idle');
  const [job, setJob] = useState<JobResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [dragover, setDragover] = useState(false);
  const pollRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const pollCount = useRef(0);
  const legacyCameraRef = useRef<HTMLInputElement>(null);
  const legacyFileRef = useRef<HTMLInputElement>(null);
  const pageCameraRef = useRef<HTMLInputElement>(null);
  const pageFileRef = useRef<HTMLInputElement>(null);
  const guidedCameraRef = useRef<HTMLInputElement>(null);
  const guidedFileRef = useRef<HTMLInputElement>(null);

  const currentChar = GUIDED_CHARACTERS[currentCharIndex] ?? 'A';
  const acceptedCount = Object.keys(acceptedGlyphs).length;
  const missingCount = GUIDED_CHARACTERS.length - acceptedCount;

  const clearPolling = useCallback(() => {
    if (pollRef.current) clearTimeout(pollRef.current);
    pollRef.current = null;
    pollCount.current = 0;
  }, []);

  useEffect(() => () => clearPolling(), [clearPolling]);

  const cleanupRef = useRef({
    legacyPreview: null as string | null,
    pagePreview: null as string | null,
    guidedPreview: null as string | null,
    currentMaskUrl: null as string | null,
    acceptedGlyphs: {} as Record<string, AcceptedGlyph>,
  });

  useEffect(() => { cleanupRef.current.legacyPreview = legacyPreview; }, [legacyPreview]);
  useEffect(() => { cleanupRef.current.pagePreview = pagePreview; }, [pagePreview]);
  useEffect(() => { cleanupRef.current.guidedPreview = guidedPreview; }, [guidedPreview]);
  useEffect(() => { cleanupRef.current.currentMaskUrl = currentMask?.url ?? null; }, [currentMask]);
  useEffect(() => { cleanupRef.current.acceptedGlyphs = acceptedGlyphs; }, [acceptedGlyphs]);
  useEffect(() => () => {
    const cleanup = cleanupRef.current;
    if (cleanup.legacyPreview) URL.revokeObjectURL(cleanup.legacyPreview);
    if (cleanup.pagePreview) URL.revokeObjectURL(cleanup.pagePreview);
    if (cleanup.guidedPreview) URL.revokeObjectURL(cleanup.guidedPreview);
    if (cleanup.currentMaskUrl) URL.revokeObjectURL(cleanup.currentMaskUrl);
    Object.values(cleanup.acceptedGlyphs).forEach((glyph) => URL.revokeObjectURL(glyph.url));
  }, []);

  useEffect(() => {
    let cancelled = false;
    let localUrl: string | null = null;
    if (guidedMaskMethod !== 'threshold' || !guidedFile || !isSupportedImage(guidedFile.type)) return undefined;

    createMaskPngFromFile(guidedFile, threshold, invert)
      .then((mask) => {
        if (cancelled) return;
        localUrl = URL.createObjectURL(mask.blob);
        setCurrentMask((previous) => {
          if (previous) URL.revokeObjectURL(previous.url);
          return { ...mask, url: localUrl ?? '' };
        });
      })
      .catch((err) => {
        if (!cancelled) {
          setCurrentMask((previous) => {
            if (previous) URL.revokeObjectURL(previous.url);
            return null;
          });
          setError(err instanceof Error ? err.message : 'Could not build a mask preview.');
        }
      });

    return () => {
      cancelled = true;
      if (localUrl) URL.revokeObjectURL(localUrl);
    };
  }, [guidedFile, guidedMaskMethod, invert, threshold]);

  function resetJobState() {
    setError(null);
    if (state === 'failed' || state === 'succeeded') {
      setState('idle');
      setJob(null);
    }
  }

  function handleLegacyFile(file: File | null) {
    if (legacyPreview) URL.revokeObjectURL(legacyPreview);
    setLegacyFile(file);
    setLegacyPreview(file ? URL.createObjectURL(file) : null);
    resetJobState();
  }

  function handlePageFile(file: File | null) {
    if (pagePreview) URL.revokeObjectURL(pagePreview);
    setPageFile(file);
    setPagePreview(file ? URL.createObjectURL(file) : null);
    setPageUploadRef(null);
    setCorners(DEFAULT_CORNERS);
    setCornersConfirmed(false);
    setCornerStatus(null);
    resetJobState();
  }

  function handleGuidedFile(file: File | null) {
    if (guidedPreview) URL.revokeObjectURL(guidedPreview);
    setGuidedFile(file);
    setGuidedPreview(file ? URL.createObjectURL(file) : null);
    setGuidedUploadRef(null);
    setForegroundStatus(null);
    setCurrentMask((previous) => {
      if (previous) URL.revokeObjectURL(previous.url);
      return null;
    });
    resetJobState();
    if (file && !isSupportedImage(file.type)) setError(ERROR_COPY.UNSUPPORTED_IMAGE_TYPE);
  }

  function editCorners(next: PageCorners) {
    setCorners(next);
    setCornersConfirmed(false);
  }

  async function pollJob(jobId: string) {
    if (pollCount.current >= MAX_POLLS) {
      setState('failed');
      setError('Job is taking too long. Check backend logs. Accepted glyphs and selected photos are still kept in this page.');
      return;
    }
    pollCount.current++;
    try {
      const res = await fetch(`/api/jobs/${encodeURIComponent(jobId)}`, { cache: 'no-store' });
      if (!res.ok) return;
      const latest = (await res.json()) as JobResponse;
      setJob(latest);
      if (latest.status === 'succeeded') {
        setState('succeeded');
        clearPolling();
        return;
      }
      if (latest.status === 'failed' || latest.status === 'expired') {
        setState('failed');
        clearPolling();
        return;
      }
      pollRef.current = setTimeout(() => pollJob(jobId), POLL_INTERVAL_MS);
    } catch {
      pollRef.current = setTimeout(() => pollJob(jobId), POLL_INTERVAL_MS * 2);
    }
  }

  async function uploadToSlot(fileOrBlob: Blob, filename: string, contentType: string): Promise<InputPhotoRef> {
    const sizeBytes = fileOrBlob.size;
    if (!isSupportedImage(contentType)) throw new Error(ERROR_COPY.UNSUPPORTED_IMAGE_TYPE);
    if (sizeBytes > MAX_UPLOAD_BYTES) throw new Error(ERROR_COPY.UPLOAD_OBJECT_TOO_LARGE);

    const uploadRes = await fetch('/api/uploads', {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ filename, contentType, sizeBytes }),
    });
    const uploadPayload = (await uploadRes.json()) as UploadResponse | { error?: { message?: string } };
    if (!uploadRes.ok || !('uploadUrl' in uploadPayload)) {
      throw new Error(('error' in uploadPayload ? uploadPayload.error?.message : undefined) ?? 'Could not prepare the upload.');
    }

    if (uploadPayload.mode === 'live' || uploadPayload.mode === 'local') {
      const put = await fetch(uploadPayload.uploadUrl, {
        method: uploadPayload.method,
        body: fileOrBlob,
        headers: { 'content-type': contentType },
      });
      if (!put.ok) throw new Error('The upload failed. Try again with a smaller or sharper image.');
    }

    return uploadRefFromSlot(uploadPayload, contentType, sizeBytes);
  }

  function validateFontAndFile(file?: File | null) {
    if (file) {
      if (!isSupportedImage(file.type)) return ERROR_COPY.UNSUPPORTED_IMAGE_TYPE;
      if (file.size > MAX_UPLOAD_BYTES) return ERROR_COPY.UPLOAD_OBJECT_TOO_LARGE;
    }
    if (!isSafeFontName(fontName)) return ERROR_COPY.FONT_METADATA_INVALID;
    return null;
  }

  async function createJob(body: CreateJobRequest) {
    setState('creating_job');
    const createRes = await fetch('/api/jobs', {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify(body),
    });
    const created = (await createRes.json()) as JobResponse | { error?: { message?: string } };
    if (!createRes.ok || !('jobId' in created)) {
      setState('failed');
      throw new Error(('error' in created ? created.error?.message : undefined) ?? 'Could not create the font job.');
    }

    setJob(created);
    if (created.status === 'succeeded') {
      setState('succeeded');
    } else if (created.status === 'failed') {
      setState('failed');
    } else {
      setState('polling');
      pollJob(created.jobId);
    }
  }

  async function submitLegacy(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError(null);
    setJob(null);
    clearPolling();
    if (!legacyFile) return setError('Choose a photographed legacy marker template image first.');
    const validation = validateFontAndFile(legacyFile);
    if (validation) return setError(validation);

    try {
      setState('preparing_upload');
      const inputPhoto = await uploadToSlot(legacyFile, legacyFile.name, legacyFile.type);
      await createJob({ inputPhoto, font: { fontName, familyName, styleName }, template: { version: 'v1' } });
    } catch (err) {
      setState('failed');
      setError(err instanceof Error ? err.message : 'An unexpected error occurred.');
    }
  }

  async function ensurePageUpload() {
    if (pageUploadRef) return pageUploadRef;
    if (!pageFile) throw new Error('Choose a photographed markerless A4 sheet first.');
    const validation = validateFontAndFile(pageFile);
    if (validation) throw new Error(validation);
    setState('preparing_upload');
    const inputPhoto = await uploadToSlot(pageFile, pageFile.name, pageFile.type);
    setPageUploadRef(inputPhoto);
    return inputPhoto;
  }

  async function ensureGuidedSourceUpload() {
    if (guidedUploadRef) return guidedUploadRef;
    if (!guidedFile) throw new Error('Capture or upload an image before extracting an object.');
    const validation = validateFontAndFile(guidedFile);
    if (validation) throw new Error(validation);
    setState('preparing_upload');
    const inputPhoto = await uploadToSlot(guidedFile, guidedFile.name, guidedFile.type);
    setGuidedUploadRef(inputPhoto);
    return inputPhoto;
  }

  async function extractObjectMask() {
    setError(null);
    setForegroundStatus(null);
    try {
      const inputPhoto = await ensureGuidedSourceUpload();
      setForegroundStatus('Extracting the selected rectangle with the backend object cutout…');
      const res = await fetch('/api/capture/foreground', {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({ inputPhoto, rectangle: foregroundRectangle }),
      });
      const payload = (await res.json()) as CaptureForegroundResponse | { error?: { message?: string } };
      if (!res.ok || !('maskDataUrl' in payload)) throw new Error(('error' in payload ? payload.error?.message : undefined) ?? 'Could not extract the object mask.');
      const blob = dataUrlToBlob(payload.maskDataUrl);
      const measured = await measureMaskBlob(blob);
      const url = URL.createObjectURL(blob);
      setCurrentMask((previous) => {
        if (previous) URL.revokeObjectURL(previous.url);
        return { ...measured, url };
      });
      setGuidedMaskMethod('object');
      setForegroundStatus(`Object cutout ready (${payload.method}). Inspect the black-and-white preview before accepting.`);
      setState('idle');
    } catch (err) {
      setState('idle');
      setForegroundStatus('Object cutout did not complete. Try a tighter rectangle, use a plain background, or switch to threshold.');
      setError(err instanceof Error ? err.message : 'Could not extract the object mask.');
    }
  }

  async function detectPageCorners() {
    setError(null);
    setCornerStatus(null);
    try {
      const inputPhoto = await ensurePageUpload();
      setCornerStatus('Asking the Python worker for page-corner suggestions…');
      const res = await fetch('/api/capture/page', {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({ inputPhoto }),
      });
      const payload = (await res.json()) as CapturePageResponse | { error?: { message?: string } };
      if (!res.ok || !('corners' in payload)) throw new Error(('error' in payload ? payload.error?.message : undefined) ?? 'Could not detect page corners.');
      setCorners(payload.corners);
      setCornersConfirmed(false);
      setCornerStatus('Corner suggestions loaded. Confirm them or adjust TL/TR/BR/BL before building.');
      setState('idle');
    } catch (err) {
      setState('idle');
      setCornerStatus('Automatic detection is unavailable. Use click, keyboard, or numeric corner edits, then confirm.');
      setError(err instanceof Error ? err.message : 'Could not detect page corners.');
    }
  }

  async function submitPage(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError(null);
    setJob(null);
    clearPolling();
    if (!pageFile) return setError('Choose a photographed markerless A4 sheet first.');
    const validation = validateFontAndFile(pageFile);
    if (validation) return setError(validation);
    if (!cornersConfirmed) return setError('Confirm the four page corners before submitting a markerless sheet job.');

    try {
      const inputPhoto = await ensurePageUpload();
      await createJob({
        inputPhoto,
        font: { fontName, familyName, styleName },
        template: { version: 'v1', templateId: 'default-v1' },
        capture: { mode: 'template', templateId: 'default-v1', paperSize: 'A4', alignment: 'page', corners },
      });
    } catch (err) {
      setState('failed');
      setError(err instanceof Error ? err.message : 'An unexpected error occurred.');
    }
  }

  function acceptCurrentGlyph() {
    setError(null);
    if (!guidedFile || !currentMask) return setError('Capture or upload an image for this character first.');
    if (currentMask.foregroundRatio < 0.001) return setError('The mask is almost blank. Lower the threshold or turn on invert before accepting.');
    if (currentMask.foregroundRatio > 0.98) return setError('The mask is almost solid black. Raise the threshold or turn off invert before accepting.');
    const storedUrl = URL.createObjectURL(currentMask.blob);
    const accepted: AcceptedGlyph = {
      char: currentChar,
      blob: currentMask.blob,
      url: storedUrl,
      baseline,
      width: currentMask.width,
      height: currentMask.height,
      foregroundRatio: currentMask.foregroundRatio,
      filename: glyphFilename(currentChar),
    };
    setAcceptedGlyphs((previous) => {
      const existing = previous[currentChar];
      if (existing) URL.revokeObjectURL(existing.url);
      return { ...previous, [currentChar]: accepted };
    });
    if (currentCharIndex < GUIDED_CHARACTERS.length - 1) setCurrentCharIndex((idx) => idx + 1);
  }

  function redoCurrentGlyph() {
    setAcceptedGlyphs((previous) => {
      const existing = previous[currentChar];
      if (!existing) return previous;
      URL.revokeObjectURL(existing.url);
      const next = { ...previous };
      delete next[currentChar];
      return next;
    });
  }

  async function submitGuided(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError(null);
    setJob(null);
    clearPolling();
    const validation = validateFontAndFile();
    if (validation) return setError(validation);
    const glyphs = GUIDED_CHARACTERS.map((char) => acceptedGlyphs[char]).filter((glyph): glyph is AcceptedGlyph => Boolean(glyph));
    if (glyphs.length < 1) return setError('Accept at least one character mask before building a guided font.');

    try {
      setState('preparing_upload');
      const uploadedGlyphs = [];
      for (const glyph of glyphs) {
        setState('uploading');
        const inputPhoto = await uploadToSlot(glyph.blob, glyph.filename, 'image/png');
        uploadedGlyphs.push({ char: glyph.char, inputPhoto, baseline: glyph.baseline });
      }
      const first = uploadedGlyphs[0];
      if (!first) throw new Error('No guided glyph masks were accepted.');
      await createJob({
        inputPhoto: first.inputPhoto,
        font: { fontName, familyName, styleName },
        template: { version: 'v1' },
        capture: { mode: 'guided', format: 'mask-v1', glyphs: uploadedGlyphs },
      });
    } catch (err) {
      setState('failed');
      setError(err instanceof Error ? err.message : 'An unexpected error occurred.');
    }
  }

  const isProcessing = state === 'preparing_upload' || state === 'uploading' || state === 'creating_job' || state === 'polling';

  return (
    <section className="grid grid-cols-1 items-start gap-6 md:grid-cols-[1.2fr_1fr]" aria-labelledby="workbench-title">
      <div className="col-span-full mb-2">
        <span className="mb-3 inline-block rounded-[4px] bg-teal-muted px-2.5 py-1 font-mono text-[11px] font-medium uppercase tracking-[.12em] text-teal">
          Build
        </span>
        <h2 id="workbench-title" className="mt-1 text-[clamp(1.8rem,3.5vw,2.8rem)] font-bold leading-none tracking-[-0.04em]">
          Capture characters for a real font build
        </h2>
        <p className="mt-2 text-sm text-text-secondary">
          Use guided character photos, a markerless A4 sheet with confirmed corners, or the original marker template. If no build worker is connected, the page will say so instead of showing fake downloads.
        </p>
      </div>

      <div className="grid gap-5 rounded-[22px] border border-border bg-surface p-7">
        <ModeChooser mode={mode} onModeChange={setMode} />
        <FontFields fontName={fontName} familyName={familyName} styleName={styleName} onFontName={setFontName} onFamilyName={setFamilyName} onStyleName={setStyleName} />

        {mode === 'guided' && (
          <form className="grid gap-5" onSubmit={submitGuided}>
            <GuidedCapturePanel
              currentChar={currentChar}
              currentCharIndex={currentCharIndex}
              acceptedGlyphs={acceptedGlyphs}
              missingCount={missingCount}
              acceptedCount={acceptedCount}
              guidedPreview={guidedPreview}
              currentMask={currentMask}
              maskMethod={guidedMaskMethod}
              foregroundRectangle={foregroundRectangle}
              foregroundStatus={foregroundStatus}
              threshold={threshold}
              invert={invert}
              baseline={baseline}
              cameraRef={guidedCameraRef}
              fileRef={guidedFileRef}
              onFile={handleGuidedFile}
              onMaskMethod={setGuidedMaskMethod}
              onForegroundRectangle={(rectangle) => setForegroundRectangle(normalizeRectangle(rectangle))}
              onExtractObject={extractObjectMask}
              onThreshold={setThreshold}
              onInvert={setInvert}
              onBaseline={setBaseline}
              onAccept={acceptCurrentGlyph}
              onRedo={redoCurrentGlyph}
              onPrevious={() => setCurrentCharIndex((idx) => Math.max(0, idx - 1))}
              onNext={() => setCurrentCharIndex((idx) => Math.min(GUIDED_CHARACTERS.length - 1, idx + 1))}
              onPickChar={(char) => setCurrentCharIndex(GUIDED_CHARACTERS.indexOf(char))}
              isProcessing={isProcessing}
            />
            {error && <ErrorMessage message={error} />}
            <button type="submit" disabled={isProcessing || acceptedCount < 1} className="primary-button">
              {isProcessing ? 'Processing…' : `Build guided font (${acceptedCount} accepted)`}
            </button>
          </form>
        )}

        {mode === 'markerless' && (
          <form className="grid gap-5" onSubmit={submitPage}>
            <FileCaptureBox
              label="Markerless A4 sheet photo"
              preview={pagePreview}
              previewAlt="Captured markerless A4 sheet preview"
              file={pageFile}
              cameraRef={pageCameraRef}
              fileRef={pageFileRef}
              dragover={dragover}
              setDragover={setDragover}
              onFile={handlePageFile}
              onRemove={() => handlePageFile(null)}
            />
            <CornerEditor
              preview={pagePreview}
              corners={corners}
              selectedCorner={selectedCorner}
              confirmed={cornersConfirmed}
              status={cornerStatus}
              onDetect={detectPageCorners}
              onSelect={setSelectedCorner}
              onChange={editCorners}
              onConfirm={() => { setCornersConfirmed(true); setCornerStatus('Confirmed the four page corners for default-v1 A4.'); }}
              isProcessing={isProcessing}
            />
            {error && <ErrorMessage message={error} />}
            <button type="submit" disabled={isProcessing || !pageFile || !cornersConfirmed} className="primary-button">
              {isProcessing ? 'Processing…' : 'Build markerless sheet font'}
            </button>
          </form>
        )}

        {mode === 'legacy' && (
          <form className="grid gap-5" onSubmit={submitLegacy}>
            <div className="rounded-xl border border-amber-200 bg-amber-muted px-4 py-3 text-[13px] text-[#92400e]">
              Legacy compatibility mode keeps the original marker-template build path for existing filled sheets.
            </div>
            <FileCaptureBox
              label="Legacy marker template photo"
              preview={legacyPreview}
              previewAlt="Captured template preview"
              file={legacyFile}
              cameraRef={legacyCameraRef}
              fileRef={legacyFileRef}
              dragover={dragover}
              setDragover={setDragover}
              onFile={handleLegacyFile}
              onRemove={() => handleLegacyFile(null)}
            />
            {error && <ErrorMessage message={error} />}
            <button type="submit" disabled={isProcessing || !legacyFile} className="primary-button">
              {isProcessing ? 'Processing…' : 'Build legacy marker font'}
            </button>
          </form>
        )}
      </div>

      <StatusPanel state={state} job={job} acceptedCharacters={mode === 'guided' ? Object.keys(acceptedGlyphs) : null} />
    </section>
  );
}

function ModeChooser({ mode, onModeChange }: { mode: WorkbenchMode; onModeChange: (mode: WorkbenchMode) => void }) {
  const modes: { key: WorkbenchMode; title: string; detail: string }[] = [
    { key: 'guided', title: 'Guided characters', detail: 'Best for partial alphabets, drawings, leaves, and redo-one-character capture.' },
    { key: 'markerless', title: 'Markerless A4 sheet', detail: 'Use default-v1 A4 page geometry and confirm TL/TR/BR/BL corners.' },
    { key: 'legacy', title: 'Legacy marker sheet', detail: 'Keep the old ArUco V1 template path for existing filled sheets.' },
  ];
  return (
    <div className="grid gap-2 sm:grid-cols-3" role="tablist" aria-label="Capture mode">
      {modes.map((item) => (
        <button
          key={item.key}
          type="button"
          role="tab"
          aria-selected={mode === item.key}
          onClick={() => onModeChange(item.key)}
          className={`rounded-xl border px-4 py-3 text-left transition-colors ${mode === item.key ? 'border-accent bg-accent text-white' : 'border-border bg-bg hover:border-border-strong'}`}
        >
          <strong className="block text-sm">{item.title}</strong>
          <span className={`mt-1 block text-xs ${mode === item.key ? 'text-white/80' : 'text-text-tertiary'}`}>{item.detail}</span>
        </button>
      ))}
    </div>
  );
}

function FontFields(props: {
  fontName: string;
  familyName: string;
  styleName: string;
  onFontName: (value: string) => void;
  onFamilyName: (value: string) => void;
  onStyleName: (value: string) => void;
}) {
  return (
    <div className="grid grid-cols-1 gap-3.5 sm:grid-cols-2">
      <label className="col-span-full grid gap-1.5">
        <span className="text-[13px] font-semibold text-text-primary">Font name</span>
        <input type="text" value={props.fontName} onChange={(e) => props.onFontName(e.target.value)} className="field" />
      </label>
      <label className="grid gap-1.5">
        <span className="text-[13px] font-semibold text-text-primary">Family name</span>
        <input type="text" value={props.familyName} onChange={(e) => props.onFamilyName(e.target.value)} className="field" />
      </label>
      <label className="grid gap-1.5">
        <span className="text-[13px] font-semibold text-text-primary">Style</span>
        <input type="text" value={props.styleName} onChange={(e) => props.onStyleName(e.target.value)} className="field" />
      </label>
    </div>
  );
}

function FileCaptureBox({ label, preview, previewAlt, file, cameraRef, fileRef, dragover, setDragover, onFile, onRemove }: {
  label: string;
  preview: string | null;
  previewAlt: string;
  file: File | null;
  cameraRef: RefObject<HTMLInputElement | null>;
  fileRef: RefObject<HTMLInputElement | null>;
  dragover: boolean;
  setDragover: (value: boolean) => void;
  onFile: (file: File | null) => void;
  onRemove: () => void;
}) {
  return (
    <div className="grid gap-2">
      <span className="text-[13px] font-semibold text-text-primary">{label}</span>
      {file && preview ? (
        <div className="relative overflow-hidden rounded-xl border border-border">
          <img src={preview} alt={previewAlt} className="h-[220px] w-full object-contain bg-bg-subtle" />
          <div className="absolute inset-x-0 bottom-0 flex items-end bg-gradient-to-t from-black/50 via-transparent p-3">
            <span className="text-xs font-medium text-white">{file.name} &middot; {(file.size / 1024 / 1024).toFixed(1)} MB</span>
          </div>
          <button type="button" onClick={onRemove} aria-label="Remove photo" className="absolute top-2 right-2 flex h-7 w-7 items-center justify-center rounded-full bg-black/60 text-white transition-colors hover:bg-black/80">
            <XIcon />
          </button>
        </div>
      ) : (
        <div
          className={`relative flex flex-col items-center justify-center gap-3 rounded-xl border-2 border-dashed px-6 py-6 transition-all duration-200 ${dragover ? 'border-teal bg-teal-muted' : 'border-border bg-bg hover:border-teal hover:bg-teal-muted'}`}
          onDragOver={(e) => { e.preventDefault(); setDragover(true); }}
          onDragLeave={() => setDragover(false)}
          onDrop={(e) => { e.preventDefault(); setDragover(false); onFile(e.dataTransfer.files[0] ?? null); }}
        >
          <div className="flex flex-wrap justify-center gap-3">
            <button type="button" onClick={() => cameraRef.current?.click()} className="secondary-button">
              <CameraIcon className="text-teal" />
              Take photo
            </button>
            <button type="button" onClick={() => fileRef.current?.click()} className="secondary-button">
              <UploadIcon className="text-text-secondary" />
              Upload file
            </button>
          </div>
          <p className="text-center text-xs text-text-tertiary">or drag and drop &middot; JPEG, PNG, WebP &middot; up to {Math.round(MAX_UPLOAD_BYTES / 1024 / 1024)} MB</p>
          <input ref={cameraRef} type="file" accept="image/jpeg,image/png,image/webp" capture="environment" className="hidden" onChange={(e) => onFile(e.target.files?.[0] ?? null)} />
          <input ref={fileRef} type="file" accept="image/jpeg,image/png,image/webp" className="hidden" onChange={(e) => onFile(e.target.files?.[0] ?? null)} />
        </div>
      )}
    </div>
  );
}

function GuidedCapturePanel({ currentChar, currentCharIndex, acceptedGlyphs, missingCount, acceptedCount, guidedPreview, currentMask, maskMethod, foregroundRectangle, foregroundStatus, threshold, invert, baseline, cameraRef, fileRef, onFile, onMaskMethod, onForegroundRectangle, onExtractObject, onThreshold, onInvert, onBaseline, onAccept, onRedo, onPrevious, onNext, onPickChar, isProcessing }: {
  currentChar: string;
  currentCharIndex: number;
  acceptedGlyphs: Record<string, AcceptedGlyph>;
  missingCount: number;
  acceptedCount: number;
  guidedPreview: string | null;
  currentMask: CurrentMask | null;
  maskMethod: GuidedMaskMethod;
  foregroundRectangle: NormalizedRectangle;
  foregroundStatus: string | null;
  threshold: number;
  invert: boolean;
  baseline: number;
  cameraRef: RefObject<HTMLInputElement | null>;
  fileRef: RefObject<HTMLInputElement | null>;
  onFile: (file: File | null) => void;
  onMaskMethod: (value: GuidedMaskMethod) => void;
  onForegroundRectangle: (value: NormalizedRectangle) => void;
  onExtractObject: () => void;
  onThreshold: (value: number) => void;
  onInvert: (value: boolean) => void;
  onBaseline: (value: number) => void;
  onAccept: () => void;
  onRedo: () => void;
  onPrevious: () => void;
  onNext: () => void;
  onPickChar: (char: string) => void;
  isProcessing: boolean;
}) {
  const acceptedCurrent = acceptedGlyphs[currentChar];
  return (
    <div className="grid gap-5">
      <div className="rounded-xl border border-border bg-bg px-4 py-3">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <span className="text-xs uppercase tracking-[.08em] text-text-tertiary">Current character</span>
            <strong className="block text-5xl leading-none">{currentChar}</strong>
          </div>
          <p className="max-w-[34ch] text-sm text-text-secondary">Photograph one dark glyph or silhouette on a contrasting background. Accepting stores the exact black-and-white preview that will be used for that character.</p>
        </div>
      </div>

      <div className="grid gap-4 md:grid-cols-2">
        <div className="grid gap-2">
          <span className="text-[13px] font-semibold text-text-primary">Source image</span>
          {guidedPreview ? (
            <div className="relative overflow-hidden rounded-xl border border-border bg-bg-subtle">
              <img src={guidedPreview} alt={`Source photo for ${currentChar}`} className="h-[240px] w-full object-contain" />
            </div>
          ) : (
            <div className="grid place-items-center gap-3 rounded-xl border-2 border-dashed border-border bg-bg px-4 py-8">
              <div className="flex flex-wrap justify-center gap-3">
                <button type="button" onClick={() => cameraRef.current?.click()} className="secondary-button"><CameraIcon className="text-teal" />Take photo</button>
                <button type="button" onClick={() => fileRef.current?.click()} className="secondary-button"><UploadIcon className="text-text-secondary" />Upload file</button>
              </div>
              <p className="text-center text-xs text-text-tertiary">Use a clear photo for the selected character only.</p>
            </div>
          )}
          {guidedPreview && (
            <div className="flex gap-2">
              <button type="button" onClick={() => cameraRef.current?.click()} className="secondary-button">Retake</button>
              <button type="button" onClick={() => fileRef.current?.click()} className="secondary-button">Replace</button>
            </div>
          )}
          <input ref={cameraRef} type="file" accept="image/jpeg,image/png,image/webp" capture="environment" className="hidden" onChange={(e) => onFile(e.target.files?.[0] ?? null)} />
          <input ref={fileRef} type="file" accept="image/jpeg,image/png,image/webp" className="hidden" onChange={(e) => onFile(e.target.files?.[0] ?? null)} />
        </div>
        <div className="grid gap-2">
          <span className="text-[13px] font-semibold text-text-primary">Accepted preview / upload image</span>
          <div className="relative grid h-[240px] place-items-center overflow-hidden rounded-xl border border-border bg-white">
            {currentMask ? (
              <>
                <img src={currentMask.url} alt={`Black-on-white mask for ${currentChar}`} className="max-h-full max-w-full object-contain [image-rendering:auto]" />
                <div className="absolute inset-x-0 border-t-2 border-dashed border-teal" style={{ top: `${baseline * 100}%` }} aria-hidden="true" />
              </>
            ) : (
              <span className="px-4 text-center text-sm text-text-tertiary">Mask preview appears after a source image is decoded.</span>
            )}
          </div>
          {currentMask && (
            <p className="text-xs text-text-tertiary">{currentMask.width}×{currentMask.height}px PNG, {(currentMask.foregroundRatio * 100).toFixed(1)}% foreground. Black pixels are character ink.</p>
          )}
        </div>
      </div>

      <div className="grid gap-3 rounded-xl border border-border bg-bg p-4">
        <fieldset className="grid gap-2">
          <legend className="text-[13px] font-semibold text-text-primary">Preview method</legend>
          <label className="flex items-start gap-2 text-sm text-text-secondary">
            <input type="radio" name="mask-method" checked={maskMethod === 'threshold'} onChange={() => onMaskMethod('threshold')} />
            <span><strong className="text-text-primary">Threshold</strong><br />Fast local black/white extraction for dark ink or interior detail on a light background.</span>
          </label>
          <label className="flex items-start gap-2 text-sm text-text-secondary">
            <input type="radio" name="mask-method" checked={maskMethod === 'object'} onChange={() => onMaskMethod('object')} />
            <span><strong className="text-text-primary">Experimental object cutout</strong><br />Backend rectangle cutout for a solid monochrome silhouette on a plain background; it does not keep original color or texture.</span>
          </label>
        </fieldset>

        {maskMethod === 'threshold' ? (
          <>
            <label className="grid gap-1.5">
              <span className="text-[13px] font-semibold text-text-primary">Threshold: {threshold}</span>
              <input type="range" min="1" max="254" step="1" value={threshold} onChange={(e) => onThreshold(Number(e.target.value))} />
            </label>
            <label className="flex items-center gap-2 text-sm text-text-secondary">
              <input type="checkbox" checked={invert} onChange={(e) => onInvert(e.target.checked)} />
              Invert foreground (use when the object is lighter than the background)
            </label>
          </>
        ) : (
          <ObjectRectangleControls rectangle={foregroundRectangle} onChange={onForegroundRectangle} onExtract={onExtractObject} disabled={!guidedPreview || isProcessing} status={foregroundStatus} />
        )}

        <label className="grid gap-1.5">
          <span className="text-[13px] font-semibold text-text-primary">Baseline from top: {baseline.toFixed(2)}</span>
          <input type="range" min="0.05" max="0.95" step="0.01" value={baseline} onChange={(e) => onBaseline(Number(e.target.value))} />
        </label>
      </div>

      <div className="flex flex-wrap gap-2">
        <button type="button" onClick={onPrevious} disabled={currentCharIndex === 0 || isProcessing} className="secondary-button">Previous</button>
        <button type="button" onClick={onAccept} disabled={!currentMask || isProcessing} className="secondary-button">Accept {currentChar}</button>
        <button type="button" onClick={onRedo} disabled={!acceptedCurrent || isProcessing} className="secondary-button">Redo {currentChar}</button>
        <button type="button" onClick={onNext} disabled={currentCharIndex === GUIDED_CHARACTERS.length - 1 || isProcessing} className="secondary-button">Next</button>
      </div>

      <div className="rounded-xl border border-border bg-bg p-4">
        <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
          <strong className="text-sm">Accepted character grid</strong>
          <span className="text-xs text-text-tertiary">{acceptedCount} accepted · {missingCount} missing</span>
        </div>
        <div className="grid grid-cols-8 gap-1 sm:grid-cols-12 md:grid-cols-16" aria-label="Guided character picker">
          {GUIDED_CHARACTERS.map((char) => {
            const glyph = acceptedGlyphs[char];
            const selected = char === currentChar;
            return (
              <button
                key={char}
                type="button"
                onClick={() => onPickChar(char)}
                className={`grid h-9 place-items-center rounded-md border text-sm font-semibold ${selected ? 'border-accent bg-accent text-white' : glyph ? 'border-green bg-green-muted text-green' : 'border-border bg-surface text-text-secondary hover:border-border-strong'}`}
                aria-label={`${char} ${glyph ? 'accepted' : 'missing'}`}
              >
                {glyph ? <img src={glyph.url} alt="" className="max-h-7 max-w-7 object-contain" /> : char}
              </button>
            );
          })}
        </div>
      </div>
    </div>
  );
}


function ObjectRectangleControls({ rectangle, onChange, onExtract, disabled, status }: {
  rectangle: NormalizedRectangle;
  onChange: (rectangle: NormalizedRectangle) => void;
  onExtract: () => void;
  disabled: boolean;
  status: string | null;
}) {
  const labels = ['Left', 'Top', 'Right', 'Bottom'] as const;
  return (
    <div className="grid gap-3 rounded-lg border border-border bg-surface p-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="text-xs text-text-secondary">Place the rectangle around the foreground object. The cutout creates a solid monochrome silhouette; holes found by segmentation are preserved, but color/texture is not. The original photo stays available so you can adjust and extract again.</p>
        <button type="button" onClick={onExtract} disabled={disabled} className="secondary-button">Extract object</button>
      </div>
      <div className="grid gap-2 sm:grid-cols-4">
        {rectangle.map((value, index) => (
          <label key={labels[index]} className="grid gap-1 text-xs font-semibold text-text-secondary">
            {labels[index]} {value.toFixed(2)}
            <input
              type="range"
              min="0"
              max="1"
              step="0.01"
              value={value}
              onChange={(e) => {
                const next = [...rectangle] as [number, number, number, number];
                next[index] = Number(e.target.value);
                onChange(next);
              }}
            />
            <input
              className="field h-8"
              type="number"
              min="0"
              max="1"
              step="0.01"
              value={value.toFixed(2)}
              onChange={(e) => {
                const next = [...rectangle] as [number, number, number, number];
                next[index] = Number(e.target.value);
                onChange(next);
              }}
            />
          </label>
        ))}
      </div>
      {status && <p className="text-xs text-text-secondary">{status}</p>}
    </div>
  );
}

function CornerEditor({ preview, corners, selectedCorner, confirmed, status, onDetect, onSelect, onChange, onConfirm, isProcessing }: {
  preview: string | null;
  corners: PageCorners;
  selectedCorner: CornerIndex;
  confirmed: boolean;
  status: string | null;
  onDetect: () => void;
  onSelect: (index: CornerIndex) => void;
  onChange: (corners: PageCorners) => void;
  onConfirm: () => void;
  isProcessing: boolean;
}) {
  const frameRef = useRef<HTMLDivElement>(null);
  const imageRef = useRef<HTMLImageElement>(null);
  const [overlayBox, setOverlayBox] = useState<RectLike | null>(null);
  const polygon = useMemo(() => corners.map(([x, y]) => `${x * 100},${y * 100}`).join(' '), [corners]);

  const updateOverlayBox = useCallback(() => {
    const frame = frameRef.current;
    const image = imageRef.current;
    if (!frame || !image) {
      setOverlayBox(null);
      return null;
    }
    const frameRect = frame.getBoundingClientRect();
    const imageRect = image.getBoundingClientRect();
    const bounds = containedImageBounds(imageRect, image.naturalWidth || image.width, image.naturalHeight || image.height);
    const next = {
      left: bounds.left - frameRect.left,
      top: bounds.top - frameRect.top,
      width: bounds.width,
      height: bounds.height,
    };
    setOverlayBox(next);
    return next;
  }, []);

  useEffect(() => {
    updateOverlayBox();
    window.addEventListener('resize', updateOverlayBox);
    return () => window.removeEventListener('resize', updateOverlayBox);
  }, [preview, updateOverlayBox]);

  function handleClick(event: MouseEvent<HTMLDivElement>) {
    if (!preview || !imageRef.current) return;
    updateOverlayBox();
    const image = imageRef.current;
    const [x, y] = normalizedPointInContainedImage(
      event.clientX,
      event.clientY,
      image.getBoundingClientRect(),
      image.naturalWidth || image.width,
      image.naturalHeight || image.height,
    );
    onChange(updateCorner(corners, selectedCorner, x, y));
  }

  function handleKey(event: KeyboardEvent<HTMLDivElement>) {
    const arrows: Record<string, [number, number]> = { ArrowLeft: [-1, 0], ArrowRight: [1, 0], ArrowUp: [0, -1], ArrowDown: [0, 1] };
    const delta = arrows[event.key];
    if (!delta) return;
    event.preventDefault();
    const step = event.shiftKey ? 0.025 : 0.005;
    const [x, y] = corners[selectedCorner];
    onChange(updateCorner(corners, selectedCorner, x + delta[0] * step, y + delta[1] * step));
  }

  return (
    <div className="grid gap-4 rounded-xl border border-border bg-bg p-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <strong className="text-sm">Markerless page corners</strong>
          <p className="mt-1 max-w-[56ch] text-xs text-text-tertiary">Use an upright default-v1 A4 sheet: top-left, top-right, bottom-right, bottom-left. Keep the full border visible, flatten the page, and confirm only after the overlay matches the oriented photo.</p>
        </div>
        <button type="button" onClick={onDetect} disabled={!preview || isProcessing} className="secondary-button">Find corners</button>
      </div>
      <div ref={frameRef} className="relative overflow-hidden rounded-xl border border-border bg-surface" onClick={handleClick} onKeyDown={handleKey} tabIndex={0} role="application" aria-label="Click or use arrow keys to move selected page corner">
        {preview ? <img ref={imageRef} src={preview} alt="Oriented page photo for corner confirmation" className="max-h-[380px] w-full object-contain" onLoad={updateOverlayBox} /> : <div className="grid h-[220px] place-items-center text-sm text-text-tertiary">Choose a sheet photo to edit corners.</div>}
        {preview && overlayBox && (
          <svg
            className="pointer-events-none absolute"
            style={{ left: overlayBox.left, top: overlayBox.top, width: overlayBox.width, height: overlayBox.height }}
            viewBox="0 0 100 100"
            preserveAspectRatio="none"
            aria-hidden="true"
          >
            <polygon points={polygon} fill="rgba(13,148,136,.12)" stroke="rgb(13,148,136)" strokeWidth="0.5" vectorEffect="non-scaling-stroke" />
            {corners.map(([x, y], index) => (
              <g key={CORNER_LABELS[index]}>
                <circle cx={x * 100} cy={y * 100} r={index === selectedCorner ? 2.2 : 1.6} fill={index === selectedCorner ? '#18181b' : '#0d9488'} />
                <text x={x * 100 + 1.2} y={y * 100 - 1.2} fontSize="4" fill="#18181b">{CORNER_LABELS[index]}</text>
              </g>
            ))}
          </svg>
        )}
      </div>
      <div className="grid gap-3 sm:grid-cols-4">
        {corners.map(([x, y], index) => (
          <fieldset key={CORNER_LABELS[index]} className={`rounded-lg border p-3 ${index === selectedCorner ? 'border-accent bg-surface' : 'border-border'}`}>
            <legend className="px-1 text-xs font-semibold">{CORNER_LABELS[index]}</legend>
            <button type="button" onClick={() => onSelect(index as CornerIndex)} className="mb-2 text-xs text-teal">Select</button>
            <label className="grid gap-1 text-xs text-text-tertiary">x
              <input className="field h-8" type="number" min="0" max="1" step="0.001" value={x.toFixed(3)} onChange={(e) => onChange(updateCorner(corners, index as CornerIndex, Number(e.target.value), y))} />
            </label>
            <label className="mt-2 grid gap-1 text-xs text-text-tertiary">y
              <input className="field h-8" type="number" min="0" max="1" step="0.001" value={y.toFixed(3)} onChange={(e) => onChange(updateCorner(corners, index as CornerIndex, x, Number(e.target.value)))} />
            </label>
          </fieldset>
        ))}
      </div>
      <div className="flex flex-wrap items-center gap-3">
        <button type="button" onClick={onConfirm} disabled={!preview || isProcessing} className="secondary-button">Confirm page corners</button>
        <span className={`text-xs ${confirmed ? 'text-green' : 'text-text-tertiary'}`}>{confirmed ? 'Confirmed for job submission.' : 'Required before markerless build.'}</span>
      </div>
      {status && <p className="text-xs text-text-secondary">{status}</p>}
    </div>
  );
}

function ErrorMessage({ message }: { message: string }) {
  return <p className="rounded-lg bg-red-muted px-3.5 py-2.5 text-[13px] text-red" role="alert">{message}</p>;
}

function StatusPanel({ state, job, acceptedCharacters }: { state: LocalState; job: JobResponse | null; acceptedCharacters: string[] | null }) {
  const currentStage = job?.stage ?? '';
  const currentIdx = stageIndex(currentStage);
  const isActive = state === 'polling' || state === 'creating_job';
  const isFailed = state === 'failed' || job?.status === 'failed';
  const isSuccess = state === 'succeeded';

  const badgeClass = isFailed
    ? 'bg-red-muted text-red'
    : isSuccess
      ? 'bg-green-muted text-green'
      : isActive
        ? 'bg-teal-muted text-teal'
        : 'bg-bg-subtle text-text-tertiary';
  const badgeLabel = isFailed ? 'Failed' : isSuccess ? 'Complete' : isActive ? 'Processing' : 'Ready';

  return (
    <aside className="grid content-start gap-5 rounded-[22px] border border-border bg-surface p-7" aria-live="polite">
      <div className="flex items-center justify-between">
        <span className="text-[13px] text-text-tertiary">Status</span>
        <span className={`inline-flex h-7 items-center gap-1.5 rounded-full px-3 font-mono text-xs font-semibold uppercase tracking-[.04em] ${badgeClass}`}>
          {badgeLabel}
        </span>
      </div>

      {(isActive || isSuccess || isFailed) && (
        <div className="grid gap-0">
          {PIPELINE_STAGES.map((stage, idx) => {
            const isDone = idx < currentIdx || isSuccess;
            const isCurrent = idx === currentIdx && isActive;
            const isError = isFailed && idx === currentIdx;

            let dotClass = 'border-2 border-border bg-surface text-text-tertiary';
            if (isDone) dotClass = 'border-2 border-green bg-green text-white';
            else if (isCurrent) dotClass = 'border-2 border-teal bg-teal text-white animate-[pulse-ring_1.5s_ease_infinite]';
            else if (isError) dotClass = 'border-2 border-red bg-red text-white';

            let labelClass = 'text-text-secondary';
            if (isDone) labelClass = 'text-text-tertiary';
            else if (isCurrent || isError) labelClass = 'text-text-primary font-medium';

            return (
              <div key={stage.key} className="grid grid-cols-[24px_1fr] gap-3 py-2">
                <div className={`flex h-6 w-6 items-center justify-center rounded-full text-[11px] font-bold transition-all duration-300 ${dotClass}`}>
                  {isDone ? <CheckIcon /> : isError ? '!' : ''}
                </div>
                <span className={`self-center text-[13px] ${labelClass}`}>{stage.label}</span>
              </div>
            );
          })}
        </div>
      )}

      {!isActive && !isSuccess && !isFailed && (
        <p className="text-[13px] text-text-tertiary">Choose a capture mode, then build with a configured Python worker.</p>
      )}

      {job?.progressLabel && <p className="rounded-lg border border-border bg-bg px-4 py-3 text-[13px] text-text-secondary">{job.progressLabel}</p>}

      {job?.error && (
        <div className="rounded-lg border border-red-200 bg-red-muted px-4 py-3.5">
          <strong className="font-mono text-xs text-red">{job.error.code}</strong>
          <p className="mt-1 text-[13px] text-[#991b1b]">{job.error.message}</p>
        </div>
      )}

      {job?.warnings && job.warnings.length > 0 && (
        <div className="rounded-lg border border-orange-200 bg-amber-muted px-4 py-3.5">
          <strong className="text-xs font-semibold text-amber">{job.warnings.length} warning{job.warnings.length > 1 ? 's' : ''}</strong>
          {job.warnings.map((w) => (
            <p key={`${w.code}-${w.glyph}`} className="mt-0.5 text-[13px] text-[#92400e]">{w.glyph ? `${w.glyph}: ` : ''}{w.message}</p>
          ))}
        </div>
      )}

      {job?.artifacts && job.artifacts.length > 0 && (
        <div className="grid gap-2">
          <strong className="mb-1 text-[13px] text-text-secondary">Downloads</strong>
          {job.artifacts.map((artifact) => (
            <a key={artifact.kind} className="flex items-center justify-between rounded-lg border border-border bg-bg px-4 py-3 text-[13px] font-semibold transition-colors hover:border-border-strong" href={artifact.url} download>
              <span>{artifact.label}</span>
              <span className="font-mono text-[11px] font-normal text-text-tertiary">{artifact.kind.toUpperCase()}</span>
            </a>
          ))}
          <a className="mt-2 text-sm font-semibold text-teal" href="/help/install-fonts">How to install in Word or PowerPoint →</a>
        </div>
      )}

      {isSuccess && job && <GeneratedProof key={job.jobId} job={job} acceptedCharacters={acceptedCharacters} />}

      <small className="text-xs text-text-tertiary">
        {job ? `This job's signed download links may expire around ${new Date(job.retentionExpiresAt).toLocaleString()}.` : 'Local/demo state is not a deletion guarantee. Configure backend retention before public use.'}
      </small>
    </aside>
  );
}

function GeneratedProof({ job, acceptedCharacters }: { job: JobResponse; acceptedCharacters: string[] | null }) {
  const defaultSample = useMemo(() => {
    if (acceptedCharacters?.length) return acceptedCharacters.slice(0, 18).join(' ');
    return 'Handmade Aa Bb 123 !?';
  }, [acceptedCharacters]);
  const [sample, setSample] = useState(defaultSample);
  const [fontFamily, setFontFamily] = useState<string | null>(null);
  const [fontError, setFontError] = useState<string | null>(null);
  const ttf = job.artifacts.find((artifact) => artifact.kind === 'ttf' && artifact.url);

  useEffect(() => {
    let cancelled = false;
    if (!ttf?.url || typeof FontFace === 'undefined') return undefined;
    const family = `generated-${job.jobId}`;
    const face = new FontFace(family, `url(${ttf.url})`);
    face.load()
      .then((loaded) => {
        if (cancelled) return;
        document.fonts.add(loaded);
        setFontFamily(family);
      })
      .catch(() => {
        if (!cancelled) setFontError('The browser could not load the generated TTF for typed proof. Download links may still be valid; verify locally.');
      });
    return () => { cancelled = true; };
  }, [job.jobId, ttf?.url]);

  const missingProofChars = useMemo(() => {
    if (!acceptedCharacters) return [];
    const accepted = new Set(acceptedCharacters);
    return Array.from(new Set(Array.from(sample).filter((char) => char !== ' ' && !accepted.has(char))));
  }, [acceptedCharacters, sample]);

  if (!ttf?.url) return null;
  return (
    <div className="rounded-lg border border-border bg-bg px-4 py-3.5">
      <strong className="text-xs font-semibold text-text-secondary">Typed proof from generated TTF</strong>
      <textarea value={sample} onChange={(e) => setSample(e.target.value)} className="field mt-2 min-h-[72px] w-full py-2" aria-label="Proof text" />
      <p className="mt-3 rounded-md bg-surface p-3 text-2xl leading-relaxed" style={fontFamily ? { fontFamily } : undefined}>{sample}</p>
      {missingProofChars.length > 0 && (
        <p className="mt-2 text-xs text-amber">This guided font only includes accepted characters. Missing from proof text: {missingProofChars.slice(0, 12).join(' ')}{missingProofChars.length > 12 ? '…' : ''}</p>
      )}
      {fontError && <p className="mt-2 text-xs text-red">{fontError}</p>}
    </div>
  );
}
