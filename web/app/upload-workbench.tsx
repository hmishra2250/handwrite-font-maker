'use client';

import { FormEvent, KeyboardEvent, MouseEvent, type RefObject, useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  ERROR_COPY,
  isSafeFontName,
  isSupportedImage,
  MAX_UPLOAD_BYTES,
  type CaptureForegroundPromptPoint,
  type CaptureForegroundRequestMethod,
  type CaptureForegroundResponse,
  type CaptureForegroundStyle,
  type CapturePageResponse,
  type CreateJobRequest,
  type InputPhotoRef,
  type JobResponse,
  type JobStage,
  type NormalizedRectangle,
  type PageCorners,
  type UploadResponse,
} from '@/lib/contracts';
import { ProjectManager } from './projects/project-manager';
import { useProjectClient } from './projects/use-projects';
import { FontReviewPanel, type ReviewGlyph } from './review/font-review-panel';
import { StarterSamplePanel, STARTER_TARGET_CHARACTERS } from './onboarding/starter-sample';
import { projectObjectUrl, type FontProject, type ProjectGlyph, type ProjectPayload } from '@/lib/projects';
import { recordFunnelEvent } from '@/lib/feedback-client';
import { DeleteJobButton } from './delete-job-button';
import { buildInkMask, type InkMaskMethod } from '@/lib/ink-mask';
import { MobileCameraButton } from './capture/mobile-camera';
import type { CaptureCandidate, CaptureCandidatesResponse } from '@/lib/capture-candidates';

type LocalState =
  | 'idle'
  | 'preparing_upload'
  | 'uploading'
  | 'creating_job'
  | 'polling'
  | 'succeeded'
  | 'failed';

type WorkbenchMode = 'guided' | 'markerless' | 'legacy';
type GuidedMaskMethod = 'threshold' | 'foreground';
type ForegroundPromptMode = 'positive' | 'negative';
type CornerIndex = 0 | 1 | 2 | 3;

type MaskResult = {
  blob: Blob;
  width: number;
  height: number;
  foregroundRatio: number;
};

type CurrentMask = MaskResult & {
  url: string;
  originalBlob: Blob;
  sourceMethod: 'threshold' | 'grabcut' | 'slimsam' | 'efficientsam' | 'candidate' | 'edited';
  modelId?: string;
  warnings: string[];
  candidateLabel?: string;
  candidateMethod?: string;
  candidateSvgDataUrl?: string;
};

type CaptureCandidateOption = CaptureCandidate & { stage: 'ink' | 'objects' };

type AcceptedGlyph = {
  char: string;
  blob: Blob;
  url: string;
  baseline: number;
  scale: number;
  spacing: number;
  width: number;
  height: number;
  foregroundRatio: number;
  filename: string;
  inputPhoto?: InputPhotoRef;
};

const POLL_INTERVAL_MS = 2000;
const MAX_POLLS = 120;
const MASK_MAX_SIDE = 1024;
const GUIDED_CHARACTER_ORDER = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789' + Array.from({ length: 94 }, (_, i) => String.fromCharCode(i + 33)).filter((char) => !/[A-Za-z0-9]/.test(char)).join('');
const ALL_GUIDED_CHARACTERS = Array.from(GUIDED_CHARACTER_ORDER);
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

export function maskCanvasPointFromClient(clientX: number, clientY: number, canvasRect: RectLike, canvasWidth: number, canvasHeight: number): [number, number] {
  const x = clamp01(canvasRect.width > 0 ? (clientX - canvasRect.left) / canvasRect.width : 0);
  const y = clamp01(canvasRect.height > 0 ? (clientY - canvasRect.top) / canvasRect.height : 0);
  return [Math.round(x * Math.max(0, canvasWidth - 1)), Math.round(y * Math.max(0, canvasHeight - 1))];
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


function normalizeTargetCharacters(value: string) {
  const seen = new Set<string>();
  const chars: string[] = [];
  for (const char of value) {
    const code = char.charCodeAt(0);
    if (char.length !== 1 || code < 33 || code > 126 || seen.has(char)) continue;
    seen.add(char);
    chars.push(char);
    if (chars.length >= 94) break;
  }
  return chars.join('') || STARTER_TARGET_CHARACTERS;
}

function clampScale(value: number) {
  return Math.min(1.5, Math.max(0.5, Number.isFinite(value) ? value : 1));
}

function clampSpacing(value: number) {
  return Math.min(0.25, Math.max(-0.05, Number.isFinite(value) ? value : 0));
}

async function blobFromObjectRef(ref: InputPhotoRef, errorMessage = 'Could not restore an accepted mask PNG from the saved project.'): Promise<Blob> {
  const response = await fetch(projectObjectUrl(ref), { cache: 'no-store' });
  if (!response.ok) throw new Error(errorMessage);
  return await response.blob();
}

function filenameFromObjectKey(objectKey: string) {
  return objectKey.split('/').pop() || 'saved-image.png';
}

async function createSyntheticMaskBlob(char: string): Promise<MaskResult> {
  const canvas = document.createElement('canvas');
  canvas.width = 220;
  canvas.height = 260;
  const ctx = canvas.getContext('2d', { willReadFrequently: true });
  if (!ctx) throw new Error('This browser could not create the starter mask.');
  ctx.fillStyle = 'white';
  ctx.fillRect(0, 0, canvas.width, canvas.height);
  ctx.fillStyle = 'black';
  ctx.font = 'bold 190px serif';
  ctx.textAlign = 'center';
  ctx.textBaseline = 'alphabetic';
  ctx.fillText(char, canvas.width / 2, 205);
  return maskResultFromCanvas(canvas);
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

export async function createMaskPngFromFile(file: Blob, threshold: number, invert: boolean, method: InkMaskMethod = 'global'): Promise<MaskResult> {
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
  const source = ctx.getImageData(0, 0, width, height);
  const mask = buildInkMask(source.data, width, height, { method, threshold, invert });
  source.data.set(mask.data);
  ctx.putImageData(source, 0, 0);

  const blob = await new Promise<Blob>((resolve, reject) => {
    canvas.toBlob((result) => {
      if (result) resolve(result);
      else reject(new Error('Could not encode the accepted mask PNG.'));
    }, 'image/png');
  });

  return { blob, width, height, foregroundRatio: mask.foreground / (width * height) };
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

function foregroundRatioFromImageData(data: ImageData) {
  let foreground = 0;
  for (let i = 0; i < data.data.length; i += 4) {
    const r = data.data[i] ?? 255;
    const g = data.data[i + 1] ?? 255;
    const b = data.data[i + 2] ?? 255;
    if ((r + g + b) / 3 < 128) foreground++;
  }
  const pixelCount = Number.isFinite(data.width) && Number.isFinite(data.height) ? data.width * data.height : data.data.length / 4;
  return foreground / Math.max(1, pixelCount);
}

async function maskResultFromCanvas(canvas: HTMLCanvasElement): Promise<MaskResult> {
  const ctx = canvas.getContext('2d', { willReadFrequently: true });
  if (!ctx) throw new Error('This browser could not read the edited mask.');
  const data = ctx.getImageData(0, 0, canvas.width, canvas.height);
  const blob = await new Promise<Blob>((resolve, reject) => {
    canvas.toBlob((result) => {
      if (result) resolve(result);
      else reject(new Error('Could not encode the edited mask PNG.'));
    }, 'image/png');
  });
  return { blob, width: canvas.width, height: canvas.height, foregroundRatio: foregroundRatioFromImageData(data) };
}

function normalizeRectangle(rectangle: NormalizedRectangle): NormalizedRectangle {
  const [left, top, right, bottom] = rectangle;
  const l = Math.min(clamp01(left), clamp01(right - 0.01));
  const t = Math.min(clamp01(top), clamp01(bottom - 0.01));
  const r = Math.max(clamp01(right), clamp01(l + 0.01));
  const b = Math.max(clamp01(bottom), clamp01(t + 0.01));
  return [l, t, r, b];
}

function describeForegroundMethod(result: CaptureForegroundResponse) {
  if (result.method === 'slimsam') return `AI model SlimSAM${result.modelId ? ` (${result.modelId})` : ''}`;
  if (result.method === 'efficientsam') return `AI box model EfficientSAM${result.modelId ? ` (${result.modelId})` : ''}`;
  if (result.method === 'threshold') return 'Fast high-contrast extraction';
  return 'classical GrabCut';
}

function describeMaskSource(mask: CurrentMask) {
  if (mask.sourceMethod === 'threshold') return 'local threshold';
  if (mask.sourceMethod === 'slimsam') return `AI model SlimSAM${mask.modelId ? ` (${mask.modelId})` : ''}`;
  if (mask.sourceMethod === 'efficientsam') return `AI box model EfficientSAM${mask.modelId ? ` (${mask.modelId})` : ''}`;
  if (mask.sourceMethod === 'candidate') return mask.candidateLabel ? `candidate option: ${mask.candidateLabel}` : 'candidate option';
  if (mask.sourceMethod === 'edited') return 'edited mask';
  return 'classical GrabCut';
}

type WorkbenchPresentation = 'studio' | 'mobile';

export function UploadWorkbench({ allowDelete = false, presentation = 'studio' }: { allowDelete?: boolean; presentation?: WorkbenchPresentation } = {}) {
  const [mode, setMode] = useState<WorkbenchMode>('guided');
  const [legacyFile, setLegacyFile] = useState<File | null>(null);
  const [legacyPreview, setLegacyPreview] = useState<string | null>(null);
  const [legacyUploadRef, setLegacyUploadRef] = useState<InputPhotoRef | null>(null);
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
  const [foregroundMethod, setForegroundMethod] = useState<CaptureForegroundRequestMethod>('auto');
  const [foregroundStyle, setForegroundStyle] = useState<CaptureForegroundStyle>('silhouette');
  const [foregroundRectangle, setForegroundRectangle] = useState<NormalizedRectangle>(DEFAULT_FOREGROUND_RECTANGLE);
  const [foregroundPoints, setForegroundPoints] = useState<CaptureForegroundPromptPoint[]>([]);
  const [foregroundPromptMode, setForegroundPromptMode] = useState<ForegroundPromptMode>('positive');
  const [foregroundStatus, setForegroundStatus] = useState<string | null>(null);
  const [inkThreshold, setInkThreshold] = useState(128);
  const [inkMaskMethod, setInkMaskMethod] = useState<InkMaskMethod>('global');
  const [threshold, setThreshold] = useState(170);
  const [invert, setInvert] = useState(false);
  const [baseline, setBaseline] = useState(0.8);
  const [currentCharIndex, setCurrentCharIndex] = useState(0);
  const [currentMask, setCurrentMask] = useState<CurrentMask | null>(null);
  const currentMaskRef = useRef<CurrentMask | null>(null);
  const [candidateOptions, setCandidateOptions] = useState<CaptureCandidateOption[]>([]);
  const [candidateFailures, setCandidateFailures] = useState<{ method: string; message: string; stage: 'ink' | 'objects' }[]>([]);
  const [candidateStatus, setCandidateStatus] = useState<string | null>(null);
  const [candidateError, setCandidateError] = useState<string | null>(null);
  const [selectedCandidateId, setSelectedCandidateId] = useState<string | null>(null);
  const [candidateObjectsPending, setCandidateObjectsPending] = useState(false);
  const [maskEditPending, setMaskEditPending] = useState(false);
  const [maskEditError, setMaskEditError] = useState<string | null>(null);
  const [acceptedGlyphs, setAcceptedGlyphs] = useState<Record<string, AcceptedGlyph>>({});
  const [fontName, setFontName] = useState('MyHandwrite-Regular');
  const [familyName, setFamilyName] = useState('My Handwrite');
  const [styleName, setStyleName] = useState('Regular');
  const [projectName, setProjectName] = useState('My first handwriting font');
  const [targetCharacters, setTargetCharacters] = useState(STARTER_TARGET_CHARACTERS);
  const [reviewSelectedChar, setReviewSelectedChar] = useState(STARTER_TARGET_CHARACTERS[0] ?? 'A');
  const [projectHydrateStatus, setProjectHydrateStatus] = useState<string | null>(null);
  const [state, setState] = useState<LocalState>('idle');
  const [job, setJob] = useState<JobResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [dragover, setDragover] = useState(false);
  const projectClient = useProjectClient();
  const { projects, activeProject, status: projectSaveStatus, message: projectMessage, createProject, openProject, saveProject, deleteProject } = projectClient;
  const pollRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const pollCount = useRef(0);
  const legacyFileRef = useRef<HTMLInputElement>(null);
  const pageFileRef = useRef<HTMLInputElement>(null);
  const guidedFileRef = useRef<HTMLInputElement>(null);
  const guidedSourceFileRef = useRef<File | null>(null);
  const guidedSourceSeq = useRef(0);
  const maskGenerationSeq = useRef(0);
  const foregroundRequestSeq = useRef(0);
  const candidateRequestSeq = useRef(0);
  const candidateSelectionSeq = useRef(0);
  const candidateAbortRef = useRef<AbortController | null>(null);
  const pageCornerRequestSeq = useRef(0);
  const activePageCornerRequestRef = useRef<number | null>(null);
  const projectSwitchSeq = useRef(0);
  const sheetSelectionSeq = useRef(0);
  const autosaveTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const autosaveChainRef = useRef<Promise<void>>(Promise.resolve());
  const activeProjectRef = useRef<FontProject | null>(null);
  const acceptedGlyphsRef = useRef<Record<string, AcceptedGlyph>>({});
  const lastSavedProjectFingerprintRef = useRef<string | null>(null);
  const pendingSaveFingerprintRef = useRef<string | null>(null);
  const hydratingProjectRef = useRef(false);
  const projectHydrationFailedRef = useRef(false);
  const recordedSuccessJobIdsRef = useRef<Set<string>>(new Set());
  const currentCharRef = useRef('A');

  const guidedCharacters = useMemo(() => Array.from(normalizeTargetCharacters(targetCharacters)), [targetCharacters]);
  const safeCurrentCharIndex = Math.min(currentCharIndex, Math.max(0, guidedCharacters.length - 1));
  const currentChar = guidedCharacters[safeCurrentCharIndex] ?? guidedCharacters[0] ?? 'A';
  currentCharRef.current = currentChar;
  const effectiveReviewSelectedChar = guidedCharacters.includes(reviewSelectedChar) ? reviewSelectedChar : guidedCharacters[0] ?? 'A';
  const acceptedCount = guidedCharacters.filter((char) => acceptedGlyphs[char]).length;
  const missingCount = Math.max(0, guidedCharacters.length - acceptedCount);

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
  useEffect(() => { guidedSourceFileRef.current = guidedFile; }, [guidedFile]);
  useEffect(() => {
    cleanupRef.current.currentMaskUrl = currentMask?.url ?? null;
    currentMaskRef.current = currentMask;
  }, [currentMask]);
  useEffect(() => {
    cleanupRef.current.acceptedGlyphs = acceptedGlyphs;
    acceptedGlyphsRef.current = acceptedGlyphs;
  }, [acceptedGlyphs]);
  useEffect(() => { activeProjectRef.current = activeProject; }, [activeProject]);
  useEffect(() => () => {
    projectSwitchSeq.current += 1;
    pageCornerRequestSeq.current += 1;
    activePageCornerRequestRef.current = null;
    activeProjectRef.current = null;
    pendingSaveFingerprintRef.current = null;
    candidateRequestSeq.current += 1;
    candidateSelectionSeq.current += 1;
    guidedSourceSeq.current += 1;
    candidateAbortRef.current?.abort();
    candidateAbortRef.current = null;
    if (autosaveTimerRef.current) clearTimeout(autosaveTimerRef.current);
    const cleanup = cleanupRef.current;
    if (cleanup.legacyPreview) URL.revokeObjectURL(cleanup.legacyPreview);
    if (cleanup.pagePreview) URL.revokeObjectURL(cleanup.pagePreview);
    if (cleanup.guidedPreview) URL.revokeObjectURL(cleanup.guidedPreview);
    if (cleanup.currentMaskUrl) URL.revokeObjectURL(cleanup.currentMaskUrl);
    Object.values(cleanup.acceptedGlyphs).forEach((glyph) => URL.revokeObjectURL(glyph.url));
  }, []);

  useEffect(() => {
    const requestId = ++maskGenerationSeq.current;
    let cancelled = false;
    let localUrl = '';
    if (guidedMaskMethod !== 'threshold' || !guidedFile || !isSupportedImage(guidedFile.type)) return undefined;

    createMaskPngFromFile(guidedFile, threshold, invert, inkMaskMethod)
      .then((mask) => {
        if (cancelled || requestId !== maskGenerationSeq.current) return;
        localUrl = URL.createObjectURL(mask.blob);
        setMaskEditPending(false);
        setMaskEditError(null);
        setSelectedCandidateId(null);
        setCurrentMask((previous) => {
          if (previous) URL.revokeObjectURL(previous.url);
          return { ...mask, url: localUrl, originalBlob: mask.blob, sourceMethod: 'threshold', warnings: [] };
        });
      })
      .catch((err) => {
        if (!cancelled && requestId === maskGenerationSeq.current) {
          setCurrentMask((previous) => {
            if (previous) URL.revokeObjectURL(previous.url);
            return null;
          });
          setMaskEditPending(false);
          setMaskEditError(null);
          setError(err instanceof Error ? err.message : 'Could not build a mask preview.');
        }
      });

    return () => {
      cancelled = true;
    };
  }, [guidedFile, guidedMaskMethod, inkMaskMethod, invert, threshold]);

  function resetJobState() {
    setError(null);
    if (state === 'failed' || state === 'succeeded') {
      setState('idle');
      setJob(null);
    }
  }

  function cancelCandidateExtraction(clear = false) {
    candidateRequestSeq.current += 1;
    candidateSelectionSeq.current += 1;
    candidateAbortRef.current?.abort();
    candidateAbortRef.current = null;
    setCandidateObjectsPending(false);
    if (clear) {
      guidedSourceSeq.current += 1;
      setCandidateOptions([]);
      setCandidateFailures([]);
      setCandidateStatus(null);
      setCandidateError(null);
      setSelectedCandidateId(null);
    }
  }

  function invalidatePageCornerDetection() {
    pageCornerRequestSeq.current += 1;
    activePageCornerRequestRef.current = null;
  }

  function isCurrentPageCornerDetection(requestId: number, switchId: number, sheetSelectionId: number) {
    return activePageCornerRequestRef.current === requestId
      && pageCornerRequestSeq.current === requestId
      && projectSwitchSeq.current === switchId
      && sheetSelectionSeq.current === sheetSelectionId;
  }

  function finishStalePageCornerDetection(requestId: number, switchId: number, sheetSelectionId: number) {
    if (isCurrentPageCornerDetection(requestId, switchId, sheetSelectionId)) return false;
    if (activePageCornerRequestRef.current === requestId) activePageCornerRequestRef.current = null;
    setState((current) => (activePageCornerRequestRef.current === null && current === 'preparing_upload' ? 'idle' : current));
    return true;
  }

  function handleModeChange(nextMode: WorkbenchMode) {
    if (nextMode !== mode) invalidatePageCornerDetection();
    setMode(nextMode);
  }

  function handleLegacyFile(file: File | null) {
    sheetSelectionSeq.current += 1;
    invalidatePageCornerDetection();
    if (legacyPreview) URL.revokeObjectURL(legacyPreview);
    setLegacyFile(file);
    setLegacyUploadRef(null);
    setLegacyPreview(file ? URL.createObjectURL(file) : null);
    resetJobState();
  }

  function handlePageFile(file: File | null) {
    sheetSelectionSeq.current += 1;
    invalidatePageCornerDetection();
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
    guidedSourceSeq.current += 1;
    guidedSourceFileRef.current = file;
    maskGenerationSeq.current++;
    foregroundRequestSeq.current++;
    cancelCandidateExtraction(true);
    if (guidedPreview) URL.revokeObjectURL(guidedPreview);
    setGuidedFile(file);
    setGuidedPreview(file ? URL.createObjectURL(file) : null);
    setGuidedUploadRef(null);
    setForegroundStatus(null);
    setForegroundPoints([]);
    setForegroundPromptMode('positive');
    setMaskEditPending(false);
    setMaskEditError(null);
    setCurrentMask((previous) => {
      if (previous) URL.revokeObjectURL(previous.url);
      return null;
    });
    resetJobState();
    if (file && !isSupportedImage(file.type)) setError(ERROR_COPY.UNSUPPORTED_IMAGE_TYPE);
  }

  function editCorners(next: PageCorners) {
    invalidatePageCornerDetection();
    setCorners(next);
    setCornersConfirmed(false);
  }

  function confirmPageCorners() {
    invalidatePageCornerDetection();
    setCornersConfirmed(true);
    setCornerStatus('Confirmed the four page corners for default-v1 A4.');
  }

  async function pollJob(jobId: string, switchId = projectSwitchSeq.current) {
    if (projectSwitchSeq.current !== switchId) return;
    if (pollCount.current >= MAX_POLLS) {
      setState('failed');
      setError('Job is taking too long. Check backend logs. Accepted glyphs and selected photos are still kept in this page.');
      return;
    }
    pollCount.current++;
    try {
      const res = await fetch(`/api/jobs/${encodeURIComponent(jobId)}`, { cache: 'no-store' });
      if (projectSwitchSeq.current !== switchId) return;
      if (!res.ok) return;
      const latest = (await res.json()) as JobResponse;
      if (projectSwitchSeq.current !== switchId) return;
      setJob(latest);
      if (latest.status === 'succeeded') {
        setState('succeeded');
        if (!recordedSuccessJobIdsRef.current.has(latest.jobId)) {
          recordedSuccessJobIdsRef.current.add(latest.jobId);
          recordFunnelEvent('build_succeeded');
        }
        clearPolling();
        return;
      }
      if (latest.status === 'failed' || latest.status === 'expired') {
        setState('failed');
        clearPolling();
        return;
      }
      pollRef.current = setTimeout(() => pollJob(jobId, switchId), POLL_INTERVAL_MS);
    } catch {
      if (projectSwitchSeq.current === switchId) pollRef.current = setTimeout(() => pollJob(jobId, switchId), POLL_INTERVAL_MS * 2);
    }
  }

  const uploadToSlot = useCallback(async (fileOrBlob: Blob, filename: string, contentType: string): Promise<InputPhotoRef> => {
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
      recordFunnelEvent('upload_complete');
    }

    return uploadRefFromSlot(uploadPayload, contentType, sizeBytes);
  }, []);

  function validateFontAndFile(file?: File | null) {
    if (file) {
      if (!isSupportedImage(file.type)) return ERROR_COPY.UNSUPPORTED_IMAGE_TYPE;
      if (file.size > MAX_UPLOAD_BYTES) return ERROR_COPY.UPLOAD_OBJECT_TOO_LARGE;
    }
    if (!isSafeFontName(fontName)) return ERROR_COPY.FONT_METADATA_INVALID;
    return null;
  }

  const projectPayloadFromGlyphs = useCallback((glyphMap: Record<string, AcceptedGlyph>, savedRefs?: { pageUploadRef?: InputPhotoRef | null; legacyUploadRef?: InputPhotoRef | null }): ProjectPayload => {
    const targets = normalizeTargetCharacters(targetCharacters);
    const targetSet = new Set(Array.from(targets));
    const savedPageUploadRef = savedRefs?.pageUploadRef ?? pageUploadRef;
    const savedLegacyUploadRef = savedRefs?.legacyUploadRef ?? legacyUploadRef;
    return {
      name: projectName.trim() || familyName || 'Untitled handwriting font',
      font: { fontName, familyName, styleName },
      mode,
      targetCharacters: targets,
      glyphs: mode === 'guided' ? Object.values(glyphMap)
        .filter((glyph) => targetSet.has(glyph.char) && glyph.inputPhoto)
        .map((glyph): ProjectGlyph => ({
          char: glyph.char,
          inputPhoto: glyph.inputPhoto as InputPhotoRef,
          baseline: glyph.baseline,
          scale: glyph.scale,
          spacing: glyph.spacing,
          width: glyph.width,
          height: glyph.height,
          foregroundRatio: glyph.foregroundRatio,
          filename: glyph.filename,
        })) : [],
      sheet: mode === 'markerless' && savedPageUploadRef ? { inputPhoto: savedPageUploadRef, corners: cornersConfirmed ? corners : undefined, cornersConfirmed } : mode === 'legacy' && savedLegacyUploadRef ? { inputPhoto: savedLegacyUploadRef } : null,
      lastJobId: job?.jobId ?? activeProjectRef.current?.lastJobId ?? null,
    };
  }, [corners, cornersConfirmed, familyName, fontName, job?.jobId, legacyUploadRef, mode, pageUploadRef, projectName, styleName, targetCharacters]);

  const projectFingerprint = useCallback((glyphMap: Record<string, AcceptedGlyph>) => {
    const targets = normalizeTargetCharacters(targetCharacters);
    const targetSet = new Set(Array.from(targets));
    return JSON.stringify({
      name: projectName.trim() || familyName || 'Untitled handwriting font',
      font: { fontName, familyName, styleName },
      mode,
      targetCharacters: targets,
      glyphs: mode === 'guided' ? Object.values(glyphMap)
        .filter((glyph) => targetSet.has(glyph.char))
        .map((glyph) => ({
          char: glyph.char,
          objectKey: glyph.inputPhoto?.objectKey ?? null,
          localSize: glyph.inputPhoto ? null : glyph.blob.size,
          baseline: glyph.baseline,
          scale: glyph.scale,
          spacing: glyph.spacing,
          width: glyph.width,
          height: glyph.height,
          foregroundRatio: glyph.foregroundRatio,
          filename: glyph.filename,
        }))
        .sort((a, b) => a.char.localeCompare(b.char)) : [],
      sheet: mode === 'markerless'
        ? pageUploadRef
          ? { objectKey: pageUploadRef.objectKey, corners: cornersConfirmed ? corners : null, cornersConfirmed }
          : pageFile
            ? { localName: pageFile.name, localSize: pageFile.size, localType: pageFile.type, corners: cornersConfirmed ? corners : null, cornersConfirmed }
            : null
        : mode === 'legacy'
          ? legacyUploadRef
            ? { objectKey: legacyUploadRef.objectKey }
            : legacyFile
              ? { localName: legacyFile.name, localSize: legacyFile.size, localType: legacyFile.type }
              : null
          : null,
      lastJobId: job?.jobId ?? activeProjectRef.current?.lastJobId ?? null,
    });
  }, [corners, cornersConfirmed, familyName, fontName, job?.jobId, legacyFile, legacyUploadRef, mode, pageFile, pageUploadRef, projectName, styleName, targetCharacters]);

  function projectFingerprintFromRemote(project: FontProject) {
    return JSON.stringify({
      name: project.name,
      font: project.font,
      mode: project.mode,
      targetCharacters: normalizeTargetCharacters(project.targetCharacters),
      glyphs: project.glyphs.map((glyph) => ({
        char: glyph.char,
        objectKey: glyph.inputPhoto.objectKey,
        localSize: null,
        baseline: glyph.baseline,
        scale: clampScale(glyph.scale ?? 1),
        spacing: clampSpacing(glyph.spacing ?? 0),
        width: glyph.width,
        height: glyph.height,
        foregroundRatio: glyph.foregroundRatio,
        filename: glyph.filename,
      })).sort((a, b) => a.char.localeCompare(b.char)),
      sheet: project.mode === 'markerless' && project.sheet ? { objectKey: project.sheet.inputPhoto.objectKey, corners: project.sheet.cornersConfirmed ? project.sheet.corners ?? null : null, cornersConfirmed: Boolean(project.sheet.cornersConfirmed) } : project.mode === 'legacy' && project.sheet ? { objectKey: project.sheet.inputPhoto.objectKey } : null,
      lastJobId: project.lastJobId ?? null,
    });
  }

  const mergeUploadedRefs = useCallback((glyphMap: Record<string, AcceptedGlyph>, uploads: { char: string; blob: Blob; inputPhoto: InputPhotoRef }[]) => {
    let nextGlyphs = glyphMap;
    for (const upload of uploads) {
      const current = nextGlyphs[upload.char];
      if (!current || current.blob !== upload.blob || current.inputPhoto) continue;
      nextGlyphs = { ...nextGlyphs, [upload.char]: { ...current, inputPhoto: upload.inputPhoto } };
    }
    return nextGlyphs;
  }, []);

  const ensureUploadedProjectGlyphs = useCallback(async (glyphMap: Record<string, AcceptedGlyph>, switchId: number) => {
    if (mode !== 'guided') return glyphMap;
    const uploads: { char: string; blob: Blob; inputPhoto: InputPhotoRef }[] = [];
    const targetSet = new Set(Array.from(normalizeTargetCharacters(targetCharacters)));
    for (const glyph of Object.values(glyphMap)) {
      if (!targetSet.has(glyph.char)) continue;
      if (projectSwitchSeq.current !== switchId) throw new Error('Project changed before the save finished.');
      if (glyph.inputPhoto) continue;
      const inputPhoto = await uploadToSlot(glyph.blob, glyph.filename, 'image/png');
      if (projectSwitchSeq.current !== switchId) throw new Error('Project changed before the upload finished.');
      uploads.push({ char: glyph.char, blob: glyph.blob, inputPhoto });
    }
    if (uploads.length === 0) return glyphMap;
    const mergedGlyphs = mergeUploadedRefs(acceptedGlyphsRef.current, uploads);
    setAcceptedGlyphs((previous) => mergeUploadedRefs(previous, uploads));
    return mergedGlyphs;
  }, [mergeUploadedRefs, mode, targetCharacters, uploadToSlot]);

  const saveActiveProject = useCallback(async (expectedFingerprint: string, scheduledProjectId: string, scheduledSwitchId: number, scheduledSheetSelection: number) => {
    const active = activeProjectRef.current;
    if (!active || active.id !== scheduledProjectId || projectSwitchSeq.current !== scheduledSwitchId || sheetSelectionSeq.current !== scheduledSheetSelection || hydratingProjectRef.current || projectHydrationFailedRef.current) return;
    const switchId = scheduledSwitchId;
    try {
      const glyphsForSave = await ensureUploadedProjectGlyphs(acceptedGlyphs, switchId);
      if (projectSwitchSeq.current !== switchId || sheetSelectionSeq.current !== scheduledSheetSelection) return;
      let savedPageUploadRef = pageUploadRef;
      let savedLegacyUploadRef = legacyUploadRef;
      if (mode === 'markerless' && !savedPageUploadRef && pageFile) {
        savedPageUploadRef = await uploadToSlot(pageFile, pageFile.name, pageFile.type);
        if (projectSwitchSeq.current !== switchId || sheetSelectionSeq.current !== scheduledSheetSelection) return;
        setPageUploadRef(savedPageUploadRef);
      }
      if (mode === 'legacy' && !savedLegacyUploadRef && legacyFile) {
        savedLegacyUploadRef = await uploadToSlot(legacyFile, legacyFile.name, legacyFile.type);
        if (projectSwitchSeq.current !== switchId || sheetSelectionSeq.current !== scheduledSheetSelection) return;
        setLegacyUploadRef(savedLegacyUploadRef);
      }
      const payload = projectPayloadFromGlyphs(glyphsForSave, { pageUploadRef: savedPageUploadRef, legacyUploadRef: savedLegacyUploadRef });
      const saved = await saveProject(active, payload);
      if (saved) {
        activeProjectRef.current = saved;
        lastSavedProjectFingerprintRef.current = projectFingerprintFromRemote(saved);
      } else if (pendingSaveFingerprintRef.current === expectedFingerprint) {
        pendingSaveFingerprintRef.current = null;
      }
    } catch (err) {
      if (projectSwitchSeq.current === switchId && activeProjectRef.current?.id === scheduledProjectId) {
        setError(err instanceof Error ? `Project autosave failed: ${err.message}` : 'Project autosave failed.');
        if (pendingSaveFingerprintRef.current === expectedFingerprint) pendingSaveFingerprintRef.current = null;
      }
    }
  }, [acceptedGlyphs, ensureUploadedProjectGlyphs, legacyFile, legacyUploadRef, mode, pageFile, pageUploadRef, projectPayloadFromGlyphs, saveProject, uploadToSlot]);

  useEffect(() => {
    if (!activeProject || hydratingProjectRef.current || projectHydrationFailedRef.current) return undefined;
    const fingerprint = projectFingerprint(acceptedGlyphs);
    if (fingerprint === lastSavedProjectFingerprintRef.current || fingerprint === pendingSaveFingerprintRef.current) return undefined;
    if (autosaveTimerRef.current) clearTimeout(autosaveTimerRef.current);
    const scheduledProjectId = activeProject.id;
    const scheduledSwitchId = projectSwitchSeq.current;
    const scheduledSheetSelection = sheetSelectionSeq.current;
    autosaveTimerRef.current = setTimeout(() => {
      pendingSaveFingerprintRef.current = fingerprint;
      autosaveChainRef.current = autosaveChainRef.current
        .then(() => saveActiveProject(fingerprint, scheduledProjectId, scheduledSwitchId, scheduledSheetSelection))
        .finally(() => { if (pendingSaveFingerprintRef.current === fingerprint) pendingSaveFingerprintRef.current = null; })
        .catch(() => undefined);
    }, 800);
    return () => {
      if (autosaveTimerRef.current) clearTimeout(autosaveTimerRef.current);
    };
  }, [acceptedGlyphs, activeProject, corners, cornersConfirmed, familyName, fontName, job?.jobId, legacyUploadRef, mode, pageUploadRef, projectFingerprint, projectName, saveActiveProject, styleName, targetCharacters]);

  async function hydrateProject(project: FontProject | null) {
    projectSwitchSeq.current += 1;
    maskGenerationSeq.current += 1;
    foregroundRequestSeq.current += 1;
    cancelCandidateExtraction(true);
    pageCornerRequestSeq.current += 1;
    activePageCornerRequestRef.current = null;
    const switchId = projectSwitchSeq.current;
    hydratingProjectRef.current = true;
    projectHydrationFailedRef.current = false;
    setProjectHydrateStatus(project ? 'Restoring project masks…' : null);
    setError(null);
    if (!project) {
      clearPolling();
      setJob(null);
      setCurrentMask((previous) => { if (previous) URL.revokeObjectURL(previous.url); return null; });
      setMaskEditPending(false);
      setMaskEditError(null);
      if (cleanupRef.current.pagePreview) URL.revokeObjectURL(cleanupRef.current.pagePreview);
      if (cleanupRef.current.legacyPreview) URL.revokeObjectURL(cleanupRef.current.legacyPreview);
      if (cleanupRef.current.guidedPreview) URL.revokeObjectURL(cleanupRef.current.guidedPreview);
      setPageFile(null);
      setPagePreview(null);
      setLegacyFile(null);
      setLegacyPreview(null);
      setGuidedFile(null);
      setGuidedPreview(null);
      setGuidedUploadRef(null);
      setMode('guided');
      setTargetCharacters(STARTER_TARGET_CHARACTERS);
      setProjectName('My first handwriting font');
      lastSavedProjectFingerprintRef.current = null;
      pendingSaveFingerprintRef.current = null;
      setAcceptedGlyphs((previous) => {
        Object.values(previous).forEach((glyph) => URL.revokeObjectURL(glyph.url));
        return {};
      });
      setCurrentCharIndex(0);
      setReviewSelectedChar(STARTER_TARGET_CHARACTERS[0] ?? 'A');
      setPageUploadRef(null);
      setLegacyUploadRef(null);
      setCorners(DEFAULT_CORNERS);
      setCornersConfirmed(false);
      hydratingProjectRef.current = false;
      return;
    }
    const targets = normalizeTargetCharacters(project.targetCharacters);
    const restoreUrls: string[] = [];
    try {
      const entries = await Promise.all(project.glyphs.map(async (glyph) => {
        const blob = await blobFromObjectRef(glyph.inputPhoto);
        const url = URL.createObjectURL(blob);
        restoreUrls.push(url);
        return [glyph.char, { ...glyph, blob, url, scale: clampScale(glyph.scale ?? 1), spacing: clampSpacing(glyph.spacing ?? 0) }] as const;
      }));
      const savedSheet = project.sheet;
      const restoredSheet = savedSheet ? await (async () => {
        const blob = await blobFromObjectRef(savedSheet.inputPhoto, 'Could not restore the saved sheet image from the saved project.');
        const url = URL.createObjectURL(blob);
        restoreUrls.push(url);
        const file = new File([blob], filenameFromObjectKey(savedSheet.inputPhoto.objectKey), { type: savedSheet.inputPhoto.contentType });
        return { file, url };
      })() : null;
      if (projectSwitchSeq.current !== switchId) {
        restoreUrls.forEach((url) => URL.revokeObjectURL(url));
        return;
      }
      let restoredJob: JobResponse | null = null;
      if (project.lastJobId) {
        const response = await fetch(`/api/jobs/${encodeURIComponent(project.lastJobId)}`, { cache: 'no-store' });
        if (projectSwitchSeq.current !== switchId) {
          restoreUrls.forEach((url) => URL.revokeObjectURL(url));
          return;
        }
        if (response.ok) restoredJob = (await response.json()) as JobResponse;
      }
      if (projectSwitchSeq.current !== switchId) {
        restoreUrls.forEach((url) => URL.revokeObjectURL(url));
        return;
      }
      clearPolling();
      setJob(null);
      setCurrentMask((previous) => { if (previous) URL.revokeObjectURL(previous.url); return null; });
      setMaskEditPending(false);
      setMaskEditError(null);
      if (cleanupRef.current.pagePreview) URL.revokeObjectURL(cleanupRef.current.pagePreview);
      if (cleanupRef.current.legacyPreview) URL.revokeObjectURL(cleanupRef.current.legacyPreview);
      if (cleanupRef.current.guidedPreview) URL.revokeObjectURL(cleanupRef.current.guidedPreview);
      setGuidedFile(null);
      setGuidedPreview(null);
      setGuidedUploadRef(null);
      setMode(project.mode);
      setProjectName(project.name);
      setFontName(project.font.fontName);
      setFamilyName(project.font.familyName);
      setStyleName(project.font.styleName);
      setTargetCharacters(targets);
      setCurrentCharIndex(0);
      setReviewSelectedChar(targets[0] ?? 'A');
      setPageFile(project.mode === 'markerless' ? restoredSheet?.file ?? null : null);
      setPagePreview(project.mode === 'markerless' ? restoredSheet?.url ?? null : null);
      setPageUploadRef(project.mode === 'markerless' ? project.sheet?.inputPhoto ?? null : null);
      setLegacyFile(project.mode === 'legacy' ? restoredSheet?.file ?? null : null);
      setLegacyPreview(project.mode === 'legacy' ? restoredSheet?.url ?? null : null);
      setLegacyUploadRef(project.mode === 'legacy' ? project.sheet?.inputPhoto ?? null : null);
      setCorners(project.sheet?.corners ?? DEFAULT_CORNERS);
      setCornersConfirmed(Boolean(project.sheet?.cornersConfirmed));
      lastSavedProjectFingerprintRef.current = projectFingerprintFromRemote(project);
      pendingSaveFingerprintRef.current = null;
      setAcceptedGlyphs((previous) => {
        Object.values(previous).forEach((glyph) => URL.revokeObjectURL(glyph.url));
        return Object.fromEntries(entries);
      });
      setProjectHydrateStatus(`Restored ${entries.length} accepted mask${entries.length === 1 ? '' : 's'}.`);
      if (restoredJob) {
        setJob(restoredJob);
        setState(restoredJob.status === 'succeeded' ? 'succeeded' : restoredJob.status === 'failed' || restoredJob.status === 'expired' ? 'failed' : 'polling');
        if (restoredJob.status !== 'succeeded' && restoredJob.status !== 'failed' && restoredJob.status !== 'expired') pollJob(restoredJob.jobId, switchId);
      } else {
        setState('idle');
      }
    } catch (err) {
      restoreUrls.forEach((url) => URL.revokeObjectURL(url));
      if (projectSwitchSeq.current === switchId) {
        projectHydrationFailedRef.current = true;
        setProjectHydrateStatus(null);
        setError(err instanceof Error ? err.message : 'Could not restore the saved project.');
      }
    } finally {
      if (projectSwitchSeq.current === switchId) hydratingProjectRef.current = false;
    }
  }

  async function createNewProject() {
    projectSwitchSeq.current += 1;
    maskGenerationSeq.current += 1;
    foregroundRequestSeq.current += 1;
    cancelCandidateExtraction(true);
    pendingSaveFingerprintRef.current = null;
    const payload: ProjectPayload = {
      name: projectName.trim() || 'My first handwriting font',
      font: { fontName, familyName, styleName },
      mode: 'guided',
      targetCharacters: STARTER_TARGET_CHARACTERS,
      glyphs: [],
      sheet: null,
      lastJobId: null,
    };
    const created = await createProject(payload);
    if (created) {
      activeProjectRef.current = created;
      lastSavedProjectFingerprintRef.current = projectFingerprintFromRemote(created);
      await hydrateProject(created);
    }
  }

  async function openSavedProject(projectId: string) {
    if (!projectId) return;
    const project = await openProject(projectId);
    if (project) {
      activeProjectRef.current = project;
      lastSavedProjectFingerprintRef.current = projectFingerprintFromRemote(project);
      await hydrateProject(project);
    }
  }

  async function deleteActiveProject() {
    const active = activeProjectRef.current;
    if (!active) return;
    if (!window.confirm(`Delete project ${active.name}? This removes the saved project but not already generated job artifacts.`)) return;
    const deleted = await deleteProject(active.id);
    if (deleted) {
      activeProjectRef.current = null;
      lastSavedProjectFingerprintRef.current = null;
      pendingSaveFingerprintRef.current = null;
      await hydrateProject(null);
    }
  }

  async function createJob(body: CreateJobRequest) {
    const switchId = projectSwitchSeq.current;
    setState('creating_job');
    const createRes = await fetch('/api/jobs', {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify(body),
    });
    const created = (await createRes.json()) as JobResponse | { error?: { message?: string } };
    if (projectSwitchSeq.current !== switchId) return;
    if (!createRes.ok || !('jobId' in created)) {
      setState('failed');
      throw new Error(('error' in created ? created.error?.message : undefined) ?? 'Could not create the font job.');
    }

    setJob(created);
    if (created.status === 'succeeded') {
      setState('succeeded');
      if (!recordedSuccessJobIdsRef.current.has(created.jobId)) {
        recordedSuccessJobIdsRef.current.add(created.jobId);
        recordFunnelEvent('build_succeeded');
      }
    } else if (created.status === 'failed') {
      setState('failed');
    } else {
      setState('polling');
      pollJob(created.jobId, switchId);
    }
  }

  async function ensureLegacyUpload() {
    if (legacyUploadRef) return legacyUploadRef;
    if (!legacyFile) throw new Error('Choose a photographed legacy marker template image first.');
    const validation = validateFontAndFile(legacyFile);
    if (validation) throw new Error(validation);
    setState('preparing_upload');
    const inputPhoto = await uploadToSlot(legacyFile, legacyFile.name, legacyFile.type);
    setLegacyUploadRef(inputPhoto);
    return inputPhoto;
  }

  async function submitLegacy(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError(null);
    setJob(null);
    clearPolling();
    if (!legacyFile && !legacyUploadRef) return setError('Choose a photographed legacy marker template image first.');
    const validation = validateFontAndFile(legacyFile);
    if (validation) return setError(validation);

    try {
      const inputPhoto = await ensureLegacyUpload();
      await createJob({ inputPhoto, font: { fontName, familyName, styleName }, template: { version: 'v1' } });
    } catch (err) {
      setState('failed');
      setError(err instanceof Error ? err.message : 'An unexpected error occurred.');
    }
  }

  async function ensurePageUpload() {
    const expectedSwitchId = projectSwitchSeq.current;
    const expectedSheetSelectionId = sheetSelectionSeq.current;
    if (pageUploadRef) return pageUploadRef;
    if (!pageFile) throw new Error('Choose a photographed markerless A4 sheet first.');
    const validation = validateFontAndFile(pageFile);
    if (validation) throw new Error(validation);
    setState('preparing_upload');
    const inputPhoto = await uploadToSlot(pageFile, pageFile.name, pageFile.type);
    if (projectSwitchSeq.current !== expectedSwitchId || sheetSelectionSeq.current !== expectedSheetSelectionId) {
      throw new Error('Sheet photo changed before the upload finished.');
    }
    setPageUploadRef(inputPhoto);
    return inputPhoto;
  }

  async function ensureGuidedSourceUpload(options: { quiet?: boolean } = {}) {
    if (guidedUploadRef) return guidedUploadRef;
    const file = guidedSourceFileRef.current ?? guidedFile;
    if (!file) throw new Error('Capture or upload an image before extracting a mask.');
    const sourceId = guidedSourceSeq.current;
    const switchId = projectSwitchSeq.current;
    const validation = validateFontAndFile(file);
    if (validation) throw new Error(validation);
    if (!options.quiet) setState('preparing_upload');
    const inputPhoto = await uploadToSlot(file, file.name, file.type);
    if (sourceId !== guidedSourceSeq.current || switchId !== projectSwitchSeq.current || guidedSourceFileRef.current !== file) {
      throw new Error('The source image changed before the upload finished.');
    }
    setGuidedUploadRef(inputPhoto);
    return inputPhoto;
  }

  function candidateKey(candidate: CaptureCandidateOption) {
    return `${candidate.stage}:${candidate.id}`;
  }

  async function applyCandidateOption(candidate: CaptureCandidateOption, requestId = candidateRequestSeq.current, char = currentCharRef.current) {
    const selectionId = ++candidateSelectionSeq.current;
    try {
      const blob = dataUrlToBlob(candidate.maskDataUrl);
      const measured = await measureMaskBlob(blob);
      if (selectionId !== candidateSelectionSeq.current || requestId !== candidateRequestSeq.current || char !== currentCharRef.current) return;
      const url = URL.createObjectURL(blob);
      setMaskEditPending(false);
      setMaskEditError(null);
      setSelectedCandidateId(candidateKey(candidate));
      setCurrentMask((previous) => {
        if (previous) URL.revokeObjectURL(previous.url);
        return {
          ...measured,
          url,
          originalBlob: blob,
          sourceMethod: 'candidate',
          warnings: candidate.warnings ?? [],
          candidateLabel: candidate.label,
          candidateMethod: candidate.method,
          candidateSvgDataUrl: candidate.svgDataUrl,
        };
      });
    } catch (err) {
      if (selectionId !== candidateSelectionSeq.current) return;
      setCandidateError(err instanceof Error ? err.message : 'Could not open this letter option.');
    }
  }

  async function fetchCandidateStage(stage: 'ink' | 'objects', requestId: number, controller: AbortController, inputPhoto: InputPhotoRef, char: string): Promise<CaptureCandidatesResponse> {
    const timeout = window.setTimeout(() => controller.abort(), 45_000);
    try {
      const response = await fetch('/api/capture/candidates', {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        signal: controller.signal,
        body: JSON.stringify({
          inputPhoto,
          rectangle: foregroundRectangle,
          stage,
          context: {
            character: char,
            baseline,
            threshold,
            invert,
            inkMaskMethod,
            foregroundMethod,
            foregroundStyle,
          },
        }),
      });
      const payload = (await response.json().catch(() => ({}))) as CaptureCandidatesResponse | { error?: { message?: string } };
      if (!response.ok || !('candidates' in payload) || !Array.isArray(payload.candidates)) {
        throw new Error(('error' in payload ? payload.error?.message : undefined) ?? 'Could not prepare letter options.');
      }
      if (requestId !== candidateRequestSeq.current || char !== currentCharRef.current) throw new Error('stale candidate response');
      return payload;
    } catch (err) {
      if (controller.signal.aborted) throw new Error(stage === 'objects' ? 'Object cutouts took too long. The fast letter options are still available.' : 'Letter options took too long. Try a simpler crop or use Advanced correction tools.');
      throw err;
    } finally {
      window.clearTimeout(timeout);
    }
  }

  async function runCandidateExtraction(file: File, char: string) {
    const requestId = ++candidateRequestSeq.current;
    candidateSelectionSeq.current += 1;
    candidateAbortRef.current?.abort();
    const controller = new AbortController();
    candidateAbortRef.current = controller;
    setCandidateOptions([]);
    setCandidateFailures([]);
    setCandidateError(null);
    setSelectedCandidateId(null);
    setCandidateObjectsPending(false);
    if (!isSupportedImage(file.type)) return;
    try {
      setCandidateStatus('Preparing letter options…');
      const inputPhoto = await ensureGuidedSourceUpload({ quiet: true });
      if (requestId !== candidateRequestSeq.current || controller.signal.aborted || char !== currentCharRef.current) return;
      const inkPayload = await fetchCandidateStage('ink', requestId, controller, inputPhoto, char);
      if (requestId !== candidateRequestSeq.current || controller.signal.aborted || char !== currentCharRef.current) return;
      const inkCandidates = inkPayload.candidates.map((candidate) => ({ ...candidate, stage: 'ink' as const }));
      setCandidateOptions(inkCandidates);
      setCandidateFailures(inkPayload.failures.map((failure) => ({ ...failure, stage: 'ink' as const })));
      if (inkCandidates[0]) void applyCandidateOption(inkCandidates[0], requestId, char);

      setCandidateStatus('Trying object cutouts…');
      setCandidateObjectsPending(true);
      try {
        const objectPayload = await fetchCandidateStage('objects', requestId, controller, inputPhoto, char);
        if (requestId !== candidateRequestSeq.current || controller.signal.aborted || char !== currentCharRef.current) return;
        const objectCandidates = objectPayload.candidates.map((candidate) => ({ ...candidate, stage: 'objects' as const }));
        setCandidateOptions((previous) => [...previous, ...objectCandidates]);
        setCandidateFailures((previous) => [...previous, ...objectPayload.failures.map((failure) => ({ ...failure, stage: 'objects' as const }))]);
        if (!inkCandidates[0] && objectCandidates[0]) void applyCandidateOption(objectCandidates[0], requestId, char);
        setCandidateError(objectPayload.failures.length > 0 ? 'Some object cutout methods failed. Pick any option that looks right.' : null);
      } catch (err) {
        if (requestId === candidateRequestSeq.current && char === currentCharRef.current) {
          setCandidateError(err instanceof Error ? err.message : 'Object cutouts failed. The fast letter options are still available.');
        }
      } finally {
        if (requestId === candidateRequestSeq.current && char === currentCharRef.current) setCandidateObjectsPending(false);
      }
      if (requestId === candidateRequestSeq.current && char === currentCharRef.current) setCandidateStatus('Choose the cleanest vector option, then accept it.');
    } catch (err) {
      if (requestId !== candidateRequestSeq.current || char !== currentCharRef.current) return;
      setCandidateStatus(null);
      setCandidateObjectsPending(false);
      setCandidateError(err instanceof Error ? err.message : 'Could not prepare letter options. The Advanced tools are still available.');
    } finally {
      if (candidateAbortRef.current === controller) candidateAbortRef.current = null;
    }
  }

  useEffect(() => {
    if (!guidedFile || !isSupportedImage(guidedFile.type)) return undefined;
    void runCandidateExtraction(guidedFile, currentCharRef.current);
    return undefined;
    // Run only when the user supplies a new source image; Advanced sliders remain manual.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [guidedFile]);

  async function extractObjectMask() {
    setError(null);
    setForegroundStatus(null);
    const requestId = ++foregroundRequestSeq.current;
    try {
      const hasPositivePoint = foregroundPoints.some((point) => point.label === 1);
      if (foregroundMethod === 'model' && !hasPositivePoint) {
        setForegroundStatus('Add at least one Keep object point on the source preview before using SlimSAM point cutout.');
        setError('Model segmentation requires at least one Keep object point.');
        return;
      }
      const effectiveMethod: CaptureForegroundRequestMethod = foregroundMethod === 'auto' && !hasPositivePoint ? 'grabcut' : foregroundMethod;
      const sendsPromptPoints = effectiveMethod === 'auto' || effectiveMethod === 'model';
      const localWarnings = foregroundMethod === 'auto' && !hasPositivePoint
        ? ['No object point was supplied; trying automatic high-contrast extraction with a bounded classical fallback.']
        : [];
      const inputPhoto = await ensureGuidedSourceUpload();
      if (requestId !== foregroundRequestSeq.current) return;
      setForegroundStatus(localWarnings[0] ?? 'Extracting the selected rectangle with the backend segmentation worker…');
      const res = await fetch('/api/capture/foreground', {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({
          inputPhoto,
          rectangle: foregroundRectangle,
          method: effectiveMethod,
          style: foregroundStyle,
          ...(foregroundStyle === 'ink' ? { threshold: inkThreshold } : {}),
          ...(sendsPromptPoints ? { points: foregroundPoints } : {}),
        }),
      });
      const payload = (await res.json()) as CaptureForegroundResponse | { error?: { message?: string } };
      if (!res.ok || !('maskDataUrl' in payload)) throw new Error(('error' in payload ? payload.error?.message : undefined) ?? 'Could not extract the segmentation mask.');
      if (requestId !== foregroundRequestSeq.current) return;
      const blob = dataUrlToBlob(payload.maskDataUrl);
      const measured = await measureMaskBlob(blob);
      if (requestId !== foregroundRequestSeq.current) return;
      const url = URL.createObjectURL(blob);
      setMaskEditPending(false);
      setMaskEditError(null);
      setCurrentMask((previous) => {
        if (previous) URL.revokeObjectURL(previous.url);
        return {
          ...measured,
          url,
          originalBlob: blob,
          sourceMethod: payload.method,
          modelId: payload.modelId,
          warnings: [...localWarnings, ...(payload.warnings ?? [])],
        };
      });
      setGuidedMaskMethod('foreground');
      setForegroundStatus(`${localWarnings[0] ? `${localWarnings[0]} ` : ''}Segmentation ready: ${describeForegroundMethod(payload)}. Inspect or correct the black-and-white preview before accepting.`);
      setState('idle');
    } catch (err) {
      if (requestId !== foregroundRequestSeq.current) return;
      setState('idle');
      setForegroundStatus('Segmentation did not complete. Try a tighter rectangle, use a plain background, or switch to threshold.');
      setError(err instanceof Error ? err.message : 'Could not extract the segmentation mask.');
    }
  }

  async function detectPageCorners() {
    setError(null);
    setCornerStatus(null);
    const requestId = ++pageCornerRequestSeq.current;
    activePageCornerRequestRef.current = requestId;
    const switchId = projectSwitchSeq.current;
    const sheetSelectionId = sheetSelectionSeq.current;
    try {
      const inputPhoto = await ensurePageUpload();
      if (finishStalePageCornerDetection(requestId, switchId, sheetSelectionId)) return;
      setCornerStatus('Asking the Python worker for page-corner suggestions…');
      const res = await fetch('/api/capture/page', {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({ inputPhoto }),
      });
      const payload = (await res.json()) as CapturePageResponse | { error?: { message?: string } };
      if (!res.ok || !('corners' in payload)) throw new Error(('error' in payload ? payload.error?.message : undefined) ?? 'Could not detect page corners.');
      if (finishStalePageCornerDetection(requestId, switchId, sheetSelectionId)) return;
      setCorners(payload.corners);
      setCornersConfirmed(false);
      setCornerStatus('Corner suggestions loaded. Confirm them or adjust TL/TR/BR/BL before building.');
      activePageCornerRequestRef.current = null;
      setState('idle');
    } catch (err) {
      if (finishStalePageCornerDetection(requestId, switchId, sheetSelectionId)) return;
      activePageCornerRequestRef.current = null;
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
    if (!pageFile && !pageUploadRef) return setError('Choose a photographed markerless A4 sheet first.');
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
    if (maskEditPending) return setError(maskEditError ?? 'Finish saving the current mask edit before accepting this character.');
    if (currentMask.foregroundRatio < 0.001) return setError('The mask is almost blank. Lower the threshold or turn on invert before accepting.');
    if (currentMask.foregroundRatio > 0.98) return setError('The mask is almost solid black. Raise the threshold or turn off invert before accepting.');
    const storedUrl = URL.createObjectURL(currentMask.blob);
    const accepted: AcceptedGlyph = {
      char: currentChar,
      blob: currentMask.blob,
      url: storedUrl,
      baseline,
      scale: 1,
      spacing: 0,
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
    setReviewSelectedChar(currentChar);
    recordFunnelEvent('glyph_accepted');
    cancelCandidateExtraction(true);
    if (currentCharIndex < guidedCharacters.length - 1) setCurrentCharIndex((idx) => idx + 1);
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

  function addForegroundPoint(x: number, y: number) {
    setForegroundPoints((previous) => {
      if (previous.length >= 16) return previous;
      return [...previous, { x: clamp01(x), y: clamp01(y), label: foregroundPromptMode === 'positive' ? 1 : 0 }];
    });
  }

  const updateCurrentMaskEdit = useCallback((mask: MaskResult, sourceUrl: string) => {
    if (currentMaskRef.current?.url !== sourceUrl) return;
    setCurrentMask((previous) => {
      if (!previous || previous.url !== sourceUrl) return previous;
      setSelectedCandidateId(null);
      return {
        ...previous,
        ...mask,
        sourceMethod: 'edited',
        candidateLabel: undefined,
        candidateMethod: undefined,
        candidateSvgDataUrl: undefined,
      };
    });
    setMaskEditPending(false);
    setMaskEditError(null);
  }, []);

  const handleMaskEditPending = useCallback((pending: boolean, message?: string | null) => {
    setMaskEditPending(pending);
    setMaskEditError(message ?? null);
  }, []);

  function updateGlyphMetrics(char: string, metrics: { baseline?: number; scale?: number; spacing?: number }) {
    setAcceptedGlyphs((previous) => {
      const glyph = previous[char];
      if (!glyph) return previous;
      return {
        ...previous,
        [char]: {
          ...glyph,
          baseline: metrics.baseline === undefined ? glyph.baseline : clamp01(metrics.baseline),
          scale: metrics.scale === undefined ? glyph.scale : clampScale(metrics.scale),
          spacing: metrics.spacing === undefined ? glyph.spacing : clampSpacing(metrics.spacing),
        },
      };
    });
    if (metrics.baseline !== undefined && char === currentChar) setBaseline(clamp01(metrics.baseline));
  }

  function handleTargetCharactersChange(value: string) {
    const normalized = normalizeTargetCharacters(value);
    cancelCandidateExtraction(true);
    setTargetCharacters(value);
    setCurrentCharIndex(0);
    setReviewSelectedChar(normalized[0] ?? 'A');
  }

  async function loadStarterSample() {
    if (hydratingProjectRef.current) {
      setError('Wait for the current project to finish opening before loading the sample.');
      return;
    }
      const switchId = ++projectSwitchSeq.current;
      maskGenerationSeq.current += 1;
      foregroundRequestSeq.current += 1;
      cancelCandidateExtraction(true);
      pageCornerRequestSeq.current += 1;
      activePageCornerRequestRef.current = null;
    projectHydrationFailedRef.current = false;
    setError(null);
    setProjectHydrateStatus('Creating bundled ABCDE sample masks…');
    lastSavedProjectFingerprintRef.current = null;
    pendingSaveFingerprintRef.current = null;
    setAcceptedGlyphs((previous) => {
      Object.values(previous).forEach((glyph) => URL.revokeObjectURL(glyph.url));
      return {};
    });
    try {
      const entries = await Promise.all(Array.from(STARTER_TARGET_CHARACTERS).map(async (char) => {
        const mask = await createSyntheticMaskBlob(char);
        const url = URL.createObjectURL(mask.blob);
        return [char, { char, ...mask, url, baseline: 0.8, scale: 1, spacing: 0, filename: glyphFilename(char) }] as const;
      }));
      if (projectSwitchSeq.current !== switchId) return;
      setMode('guided');
      setTargetCharacters(STARTER_TARGET_CHARACTERS);
      setCurrentCharIndex(0);
      setReviewSelectedChar(STARTER_TARGET_CHARACTERS[0] ?? 'A');
      setAcceptedGlyphs((previous) => {
        Object.values(previous).forEach((glyph) => URL.revokeObjectURL(glyph.url));
        return Object.fromEntries(entries);
      });
      setProjectHydrateStatus('Loaded bundled ABCDE sample masks. Replace them with handwriting photos for a real personal font.');
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not load the starter sample.');
      setProjectHydrateStatus(null);
    }
  }

  const reviewGlyphs: ReviewGlyph[] = guidedCharacters.map((char) => {
    const glyph = acceptedGlyphs[char];
    return {
      char,
      accepted: Boolean(glyph),
      baseline: glyph?.baseline,
      scale: glyph?.scale,
      spacing: glyph?.spacing,
      foregroundRatio: glyph?.foregroundRatio,
      url: glyph?.url,
    };
  });

  const isProjectBusy = projectSaveStatus === 'saving' || projectSaveStatus === 'loading' || hydratingProjectRef.current
    || state === 'preparing_upload' || state === 'uploading' || state === 'creating_job' || state === 'polling';

  async function submitGuided(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError(null);
    setJob(null);
    clearPolling();
    const validation = validateFontAndFile();
    if (validation) return setError(validation);
    const glyphs = guidedCharacters.map((char) => acceptedGlyphs[char]).filter((glyph): glyph is AcceptedGlyph => Boolean(glyph));
    if (glyphs.length < 1) return setError('Accept at least one character mask before building a guided font.');

    try {
      setState('preparing_upload');
      const switchId = projectSwitchSeq.current;
      const uploads: { char: string; blob: Blob; inputPhoto: InputPhotoRef }[] = [];
      for (const glyph of glyphs) {
        if (projectSwitchSeq.current !== switchId) return;
        setState('uploading');
        if (!glyph.inputPhoto) {
          const inputPhoto = await uploadToSlot(glyph.blob, glyph.filename, 'image/png');
          if (projectSwitchSeq.current !== switchId) return;
          uploads.push({ char: glyph.char, blob: glyph.blob, inputPhoto });
        }
      }
      const nextGlyphMap = mergeUploadedRefs(acceptedGlyphsRef.current, uploads);
      setAcceptedGlyphs(nextGlyphMap);
      const uploadedGlyphs = guidedCharacters
        .map((char) => nextGlyphMap[char])
        .filter((glyph): glyph is AcceptedGlyph & { inputPhoto: InputPhotoRef } => Boolean(glyph?.inputPhoto))
        .map((glyph) => ({ char: glyph.char, inputPhoto: glyph.inputPhoto, baseline: glyph.baseline, scale: glyph.scale, spacing: glyph.spacing }));
      const first = uploadedGlyphs[0];
      if (!first) throw new Error('No guided glyph masks were accepted.');
      await createJob({
        inputPhoto: first.inputPhoto,
        font: { fontName, familyName, styleName },
        template: { version: 'v1' },
        capture: { mode: 'guided', format: 'mask-v1', glyphs: uploadedGlyphs },
      } as CreateJobRequest);
    } catch (err) {
      setState('failed');
      setError(err instanceof Error ? err.message : 'An unexpected error occurred.');
    }
  }

  const isProcessing = state === 'preparing_upload' || state === 'uploading' || state === 'creating_job' || state === 'polling';
  const isMobilePresentation = presentation === 'mobile';

  return (
    <section className={`studio-workbench grid min-w-0 grid-cols-1 items-start [overflow-wrap:anywhere] gap-4 ${isMobilePresentation ? 'mobile-workbench mx-auto w-full max-w-[760px]' : 'xl:grid-cols-[minmax(0,1fr)_320px]'}`} aria-labelledby="workbench-title">
      <div className="col-span-full flex min-w-0 flex-wrap items-end justify-between gap-3">
        <div className="min-w-0">
          <p className="font-mono text-[11px] font-semibold uppercase tracking-[.14em] text-text-tertiary">{isMobilePresentation ? 'Phone capture alpha' : 'Private alpha studio'}</p>
          <h1 id="workbench-title" className="mt-1 text-[clamp(1.75rem,3vw,2rem)] font-bold leading-[.98] tracking-[-0.045em]">
            {isMobilePresentation ? 'Capture your font' : 'Create your font'}
          </h1>
        </div>
        {!isMobilePresentation && <p className="max-w-[42ch] text-sm text-text-secondary">Your handwriting. Found shapes. A font only you could make.</p>}
      </div>

      <div className="col-span-full">
        <ProjectManager
          projects={projects}
          activeProject={activeProject}
          projectName={projectName}
          status={projectSaveStatus}
          message={projectMessage ?? projectHydrateStatus}
          busy={isProjectBusy}
          onProjectName={setProjectName}
          onNew={createNewProject}
          onOpen={openSavedProject}
          onDelete={deleteActiveProject}
        />
      </div>

      <div className="studio-capture-panel grid min-w-0 grid-cols-1 gap-4 rounded-[26px] border border-border bg-surface p-4 shadow-[0_20px_70px_rgba(24,24,27,0.06)] sm:p-5">
        <ModeChooser mode={mode} onModeChange={handleModeChange} />
        <details className="group rounded-2xl border border-border bg-bg p-3">
          <summary className="cursor-pointer list-none text-sm font-semibold text-text-primary outline-none focus-visible:ring-2 focus-visible:ring-teal group-open:mb-3">
            Font settings
            <span className="ml-2 font-normal text-text-tertiary">{fontName} · {normalizeTargetCharacters(targetCharacters).length} characters</span>
          </summary>
          <div className="grid gap-3">
            <FontFields fontName={fontName} familyName={familyName} styleName={styleName} onFontName={setFontName} onFamilyName={setFamilyName} onStyleName={setStyleName} />
            <StudioSetupControls
              targetCharacters={targetCharacters}
              normalizedTargetCharacters={normalizeTargetCharacters(targetCharacters)}
              onTargetCharactersChange={handleTargetCharactersChange}
              sampleDisabled={isProjectBusy}
              onLoadSample={loadStarterSample}
            />
          </div>
        </details>

        {mode === 'guided' && (
          <form className="grid min-w-0 grid-cols-1 gap-5" onSubmit={submitGuided}>
            <GuidedCapturePanel
              currentChar={currentChar}
              currentCharIndex={safeCurrentCharIndex}
              guidedCharacters={guidedCharacters}
              acceptedGlyphs={acceptedGlyphs}
              missingCount={missingCount}
              acceptedCount={acceptedCount}
              guidedPreview={guidedPreview}
              currentMask={currentMask}
              candidateOptions={candidateOptions}
              selectedCandidateId={selectedCandidateId}
              candidateFailures={candidateFailures}
              candidateStatus={candidateStatus}
              candidateError={candidateError}
              candidateObjectsPending={candidateObjectsPending}
              maskEditPending={maskEditPending}
              maskEditError={maskEditError}
              maskMethod={guidedMaskMethod}
              foregroundMethod={foregroundMethod}
              foregroundStyle={foregroundStyle}
              foregroundRectangle={foregroundRectangle}
              foregroundPoints={foregroundPoints}
              foregroundPromptMode={foregroundPromptMode}
              foregroundStatus={foregroundStatus}
              inkThreshold={inkThreshold}
              inkMaskMethod={inkMaskMethod}
              threshold={threshold}
              invert={invert}
              baseline={baseline}
              fileRef={guidedFileRef}
              onFile={handleGuidedFile}
              onMaskMethod={setGuidedMaskMethod}
              onForegroundMethod={setForegroundMethod}
              onForegroundStyle={setForegroundStyle}
              onForegroundRectangle={(rectangle) => setForegroundRectangle(normalizeRectangle(rectangle))}
              onForegroundPoint={addForegroundPoint}
              onForegroundPromptMode={setForegroundPromptMode}
              onClearForegroundPoints={() => setForegroundPoints([])}
              onExtractObject={extractObjectMask}
              onInkThreshold={(value) => setInkThreshold(Math.min(254, Math.max(1, Math.round(value))))}
              onInkMaskMethod={setInkMaskMethod}
              onThreshold={setThreshold}
              onInvert={setInvert}
              onBaseline={setBaseline}
              onMaskEdited={updateCurrentMaskEdit}
              onMaskEditPending={handleMaskEditPending}
              onCandidateSelect={(candidate) => { void applyCandidateOption(candidate); }}
              onAccept={acceptCurrentGlyph}
              onRedo={redoCurrentGlyph}
              onPrevious={() => { cancelCandidateExtraction(true); setCurrentCharIndex((idx) => Math.max(0, Math.min(idx - 1, guidedCharacters.length - 1))); }}
              onNext={() => { cancelCandidateExtraction(true); setCurrentCharIndex((idx) => Math.min(Math.max(0, guidedCharacters.length - 1), idx + 1)); }}
              onPickChar={(char) => { cancelCandidateExtraction(true); setCurrentCharIndex(Math.max(0, guidedCharacters.indexOf(char))); }}
              isProcessing={isProcessing}
            />
            {acceptedCount > 0 && <FontReviewPanel glyphs={reviewGlyphs} selectedChar={effectiveReviewSelectedChar} onSelect={(char) => { setReviewSelectedChar(char); setCurrentCharIndex(Math.max(0, guidedCharacters.indexOf(char))); }} onMetricsChange={updateGlyphMetrics} />}
            {error && <ErrorMessage message={error} />}
            <button type="submit" disabled={isProcessing || isProjectBusy || acceptedCount < 1} className="primary-button">
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
              fileRef={pageFileRef}
              dragover={dragover}
              setDragover={setDragover}
              onFile={handlePageFile}
              onRemove={() => handlePageFile(null)}
            />
            {pageUploadRef && !pageFile && (
              <p className="text-xs text-text-tertiary">
                Restored saved markerless sheet upload. Build reuses the saved object without reuploading.
              </p>
            )}
            <CornerEditor
              preview={pagePreview}
              corners={corners}
              selectedCorner={selectedCorner}
              confirmed={cornersConfirmed}
              status={cornerStatus}
              onDetect={detectPageCorners}
              onSelect={setSelectedCorner}
              onChange={editCorners}
              onConfirm={confirmPageCorners}
              isProcessing={isProcessing}
            />
            {error && <ErrorMessage message={error} />}
            <button type="submit" disabled={isProcessing || isProjectBusy || (!pageFile && !pageUploadRef) || !cornersConfirmed} className="primary-button">
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
              fileRef={legacyFileRef}
              dragover={dragover}
              setDragover={setDragover}
              onFile={handleLegacyFile}
              onRemove={() => handleLegacyFile(null)}
            />
            {legacyUploadRef && !legacyFile && (
              <p className="text-xs text-text-tertiary">
                Restored saved legacy sheet upload. Build reuses the saved object without reuploading.
              </p>
            )}
            {error && <ErrorMessage message={error} />}
            <button type="submit" disabled={isProcessing || isProjectBusy || (!legacyFile && !legacyUploadRef)} className="primary-button">
              {isProcessing ? 'Processing…' : 'Build legacy marker font'}
            </button>
          </form>
        )}
      </div>

      <StatusPanel allowDelete={allowDelete} onDeleted={() => { setPageUploadRef(null); setGuidedUploadRef(null); }} state={state} job={job} acceptedCharacters={mode === 'guided' ? Object.keys(acceptedGlyphs) : null} />
    </section>
  );
}

function StudioSetupControls({ targetCharacters, normalizedTargetCharacters, onTargetCharactersChange, sampleDisabled, onLoadSample }: {
  targetCharacters: string;
  normalizedTargetCharacters: string;
  onTargetCharactersChange: (value: string) => void;
  sampleDisabled: boolean;
  onLoadSample: () => void;
}) {
  return (
    <section className="grid gap-2 rounded-2xl border border-border bg-bg p-3" aria-label="Studio setup">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <strong className="text-sm">Quick start</strong>
          <p className="mt-0.5 text-xs text-text-tertiary">Start with ABCDE on phone; expand characters when the capture quality looks right.</p>
        </div>
        <StarterSamplePanel disabled={sampleDisabled} onLoadSample={onLoadSample} />
      </div>
      <details className="group rounded-xl border border-border bg-surface px-3 py-2">
        <summary className="cursor-pointer list-none text-sm font-semibold text-text-primary outline-none focus-visible:ring-2 focus-visible:ring-teal group-open:mb-3">
          Characters and samples
          <span className="ml-2 font-normal text-text-tertiary">({normalizedTargetCharacters.length} targets)</span>
        </summary>
        <TargetCharacterControls value={targetCharacters} normalizedValue={normalizedTargetCharacters} onChange={onTargetCharactersChange} />
      </details>
    </section>
  );
}

function TargetCharacterControls({ value, normalizedValue, onChange }: { value: string; normalizedValue: string; onChange: (value: string) => void }) {
  return (
    <section className="grid gap-3" aria-label="Target characters">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div>
          <strong className="text-sm">Target characters</strong>
          <p className="mt-1 text-xs text-text-tertiary">Starter default is ABCDE. Use unique printable characters, or paste the full 94-character set when ready.</p>
        </div>
        <button type="button" className="secondary-button" onClick={() => onChange(ALL_GUIDED_CHARACTERS.join(''))}>Use full 94</button>
      </div>
      <label className="grid min-w-0 gap-1.5">
        <span className="text-[13px] font-semibold text-text-primary">Characters to capture</span>
        <input className="field font-mono" value={value} onChange={(event) => onChange(event.target.value)} aria-label="Characters to capture" />
      </label>
      <p className="text-xs text-text-tertiary">Normalized target: {normalizedValue.split('').join(' ')} · {normalizedValue.length} character{normalizedValue.length === 1 ? '' : 's'}</p>
    </section>
  );
}

function ModeChooser({ mode, onModeChange }: { mode: WorkbenchMode; onModeChange: (mode: WorkbenchMode) => void }) {
  const modes: { key: WorkbenchMode; title: string; visibleTitle: string; detail: string }[] = [
    { key: 'guided', title: 'Guided characters', visibleTitle: 'Guided', detail: 'One by one' },
    { key: 'markerless', title: 'Markerless A4 sheet', visibleTitle: 'Full sheet', detail: 'No markers' },
    { key: 'legacy', title: 'Legacy marker sheet', visibleTitle: 'Legacy', detail: 'Markers' },
  ];
  return (
    <div className="grid min-w-0 grid-cols-3 gap-1 rounded-2xl border border-border bg-bg p-1" role="tablist" aria-label="Capture mode">
      {modes.map((item) => (
        <button
          key={item.key}
          type="button"
          role="tab"
          aria-label={item.title}
          aria-selected={mode === item.key}
          onClick={() => onModeChange(item.key)}
          className={`rounded-xl border px-2 py-2 text-center transition-colors ${mode === item.key ? 'border-accent bg-accent text-white shadow-sm' : 'border-transparent bg-transparent hover:border-border-strong hover:bg-surface'}`}
        >
          <strong className="block text-[13px] sm:text-sm">{item.visibleTitle}</strong>
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
    <section className="grid gap-2 rounded-2xl border border-border bg-bg p-3" aria-label="Font metadata">
      <label className="grid gap-1.5 sm:grid-cols-[100px_minmax(0,1fr)] sm:items-center">
        <span className="text-[13px] font-semibold text-text-primary">Font name</span>
        <input type="text" value={props.fontName} onChange={(e) => props.onFontName(e.target.value)} className="field h-10" />
      </label>
      <details className="group rounded-xl border border-border bg-surface px-3 py-2">
        <summary className="cursor-pointer list-none text-sm font-semibold text-text-primary outline-none focus-visible:ring-2 focus-visible:ring-teal group-open:mb-3">
          Family and style
          <span className="ml-2 font-normal text-text-tertiary">{props.familyName} · {props.styleName}</span>
        </summary>
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
          <label className="grid gap-1.5">
            <span className="text-[13px] font-semibold text-text-primary">Family name</span>
            <input type="text" value={props.familyName} onChange={(e) => props.onFamilyName(e.target.value)} className="field" />
          </label>
          <label className="grid gap-1.5">
            <span className="text-[13px] font-semibold text-text-primary">Style</span>
            <input type="text" value={props.styleName} onChange={(e) => props.onStyleName(e.target.value)} className="field" />
          </label>
        </div>
      </details>
    </section>
  );
}

function FileCaptureBox({ label, preview, previewAlt, file, fileRef, dragover, setDragover, onFile, onRemove }: {
  label: string;
  preview: string | null;
  previewAlt: string;
  file: File | null;
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
            <MobileCameraButton onCapture={onFile} className="primary-button" />
            <button type="button" onClick={() => fileRef.current?.click()} className="primary-button">
              <UploadIcon className="text-white" />
              Upload file
            </button>
          </div>
          <p className="text-center text-xs text-text-tertiary">or drag and drop &middot; JPEG, PNG, WebP &middot; up to {Math.round(MAX_UPLOAD_BYTES / 1024 / 1024)} MB</p>
          <input ref={fileRef} type="file" accept="image/jpeg,image/png,image/webp" className="hidden" onChange={(e) => onFile(e.target.files?.[0] ?? null)} />
        </div>
      )}
    </div>
  );
}

function GuidedCapturePanel({ currentChar, currentCharIndex, guidedCharacters, acceptedGlyphs, missingCount, acceptedCount, guidedPreview, currentMask, candidateOptions, selectedCandidateId, candidateFailures, candidateStatus, candidateError, candidateObjectsPending, maskEditPending, maskEditError, maskMethod, foregroundMethod, foregroundStyle, foregroundRectangle, foregroundPoints, foregroundPromptMode, foregroundStatus, inkThreshold, inkMaskMethod, threshold, invert, baseline, fileRef, onFile, onMaskMethod, onForegroundMethod, onForegroundStyle, onForegroundRectangle, onForegroundPoint, onForegroundPromptMode, onClearForegroundPoints, onExtractObject, onInkThreshold, onInkMaskMethod, onThreshold, onInvert, onBaseline, onMaskEdited, onMaskEditPending, onCandidateSelect, onAccept, onRedo, onPrevious, onNext, onPickChar, isProcessing }: {
  currentChar: string;
  currentCharIndex: number;
  guidedCharacters: string[];
  acceptedGlyphs: Record<string, AcceptedGlyph>;
  missingCount: number;
  acceptedCount: number;
  guidedPreview: string | null;
  currentMask: CurrentMask | null;
  candidateOptions: CaptureCandidateOption[];
  selectedCandidateId: string | null;
  candidateFailures: { method: string; message: string; stage: 'ink' | 'objects' }[];
  candidateStatus: string | null;
  candidateError: string | null;
  candidateObjectsPending: boolean;
  maskEditPending: boolean;
  maskEditError: string | null;
  maskMethod: GuidedMaskMethod;
  foregroundMethod: CaptureForegroundRequestMethod;
  foregroundStyle: CaptureForegroundStyle;
  foregroundRectangle: NormalizedRectangle;
  foregroundPoints: CaptureForegroundPromptPoint[];
  foregroundPromptMode: ForegroundPromptMode;
  foregroundStatus: string | null;
  inkThreshold: number;
  inkMaskMethod: InkMaskMethod;
  threshold: number;
  invert: boolean;
  baseline: number;
  fileRef: RefObject<HTMLInputElement | null>;
  onFile: (file: File | null) => void;
  onMaskMethod: (value: GuidedMaskMethod) => void;
  onForegroundMethod: (value: CaptureForegroundRequestMethod) => void;
  onForegroundStyle: (value: CaptureForegroundStyle) => void;
  onForegroundRectangle: (value: NormalizedRectangle) => void;
  onForegroundPoint: (x: number, y: number) => void;
  onForegroundPromptMode: (mode: ForegroundPromptMode) => void;
  onClearForegroundPoints: () => void;
  onExtractObject: () => void;
  onInkThreshold: (value: number) => void;
  onInkMaskMethod: (method: InkMaskMethod) => void;
  onThreshold: (value: number) => void;
  onInvert: (value: boolean) => void;
  onBaseline: (value: number) => void;
  onMaskEdited: (mask: MaskResult, sourceUrl: string) => void;
  onMaskEditPending: (pending: boolean, message?: string | null) => void;
  onCandidateSelect: (candidate: CaptureCandidateOption) => void;
  onAccept: () => void;
  onRedo: () => void;
  onPrevious: () => void;
  onNext: () => void;
  onPickChar: (char: string) => void;
  isProcessing: boolean;
}) {
  const acceptedCurrent = acceptedGlyphs[currentChar];
  const promptPointsApply = foregroundMethod === 'auto' || foregroundMethod === 'model';

  return (
    <div className="grid min-w-0 grid-cols-1 gap-4">
      <div className="flex min-w-0 flex-wrap items-center justify-between gap-2 rounded-2xl border border-border bg-bg p-3">
        <div className="min-w-0">
          <p className="font-mono text-[11px] font-semibold uppercase tracking-[.12em] text-text-tertiary">Step {currentCharIndex + 1} of {guidedCharacters.length}</p>
          <strong className="mt-0.5 block text-[36px] font-bold leading-none tracking-[-0.04em]">Capture {currentChar}</strong>
          <p className="mt-1 text-sm text-text-secondary">Use ink, a light-on-dark mark, or any distinct shape on a clear background.</p>
        </div>
        <div className="flex flex-wrap gap-2">
          <button type="button" onClick={onPrevious} disabled={currentCharIndex === 0 || isProcessing} className="secondary-button">Previous</button>
          <button type="button" onClick={onNext} disabled={currentCharIndex === guidedCharacters.length - 1 || isProcessing} className="secondary-button">Next</button>
        </div>
      </div>

      {!guidedPreview ? (
        <div className="grid min-h-[170px] place-items-center rounded-[24px] border-2 border-dashed border-border bg-bg px-4 py-4 text-center">
          <div className="grid max-w-[420px] gap-3">
            <div className="flex flex-wrap justify-center gap-3">
              <MobileCameraButton key={currentChar} onCapture={onFile} className="primary-button" />
              <button type="button" onClick={() => fileRef.current?.click()} className="primary-button"><UploadIcon className="text-white" />Upload file</button>
            </div>
            <div>
              <strong className="text-base">Add one image for {currentChar}</strong>
              <p className="mt-1 text-sm text-text-secondary">The accepted preview becomes this character in the font.</p>
            </div>
            <p className="text-xs text-text-tertiary">JPEG, PNG, or WebP up to {Math.round(MAX_UPLOAD_BYTES / 1024 / 1024)} MB.</p>
          </div>
          <input ref={fileRef} type="file" accept="image/jpeg,image/png,image/webp" className="hidden" onChange={(e) => onFile(e.target.files?.[0] ?? null)} />
        </div>
      ) : (
        <div className="grid min-w-0 grid-cols-1 gap-4 lg:grid-cols-[minmax(0,1fr)_minmax(280px,0.82fr)]">
          <div className="grid min-w-0 gap-2">
            <div className="flex items-center justify-between gap-2">
              <span className="text-[13px] font-semibold text-text-primary">Source image</span>
              <div className="flex gap-2">
                <MobileCameraButton key={currentChar} onCapture={onFile} label="Retake" className="secondary-button shrink-0 whitespace-nowrap" />
                <button type="button" onClick={() => fileRef.current?.click()} className="primary-button">Replace</button>
              </div>
            </div>
            {maskMethod === 'foreground' && promptPointsApply ? (
              <PromptPointEditor
                preview={guidedPreview}
                currentChar={currentChar}
                points={foregroundPoints}
                promptMode={foregroundPromptMode}
                onPromptMode={onForegroundPromptMode}
                onAddPoint={onForegroundPoint}
                onClearPoints={onClearForegroundPoints}
              />
            ) : (
              <div className="relative min-w-0 overflow-hidden rounded-2xl border border-border bg-bg-subtle">
                <img src={guidedPreview} alt={`Source photo for ${currentChar}`} className="h-[260px] w-full object-contain" />
              </div>
            )}
            <input ref={fileRef} type="file" accept="image/jpeg,image/png,image/webp" className="hidden" onChange={(e) => onFile(e.target.files?.[0] ?? null)} />
          </div>
          <div className="grid min-w-0 gap-2">
            {candidateOptions.length > 0 ? (
              <CandidatePicker
                currentChar={currentChar}
                candidates={candidateOptions}
                selectedId={selectedCandidateId}
                failures={candidateFailures}
                status={candidateStatus}
                error={candidateError}
                objectsPending={candidateObjectsPending}
                onSelect={onCandidateSelect}
              />
            ) : (
              <>
                <span className="text-[13px] font-semibold text-text-primary">Font mask</span>
                <div className="relative grid min-h-[260px] min-w-0 place-items-center overflow-hidden rounded-2xl border border-border bg-white">
                  {candidateStatus ? (
                    <span className="px-4 text-center text-sm text-text-tertiary" role="status">{candidateStatus}</span>
                  ) : currentMask ? (
                    <MaskCanvasEditor key={currentMask.url} mask={currentMask} currentChar={currentChar} baseline={baseline} onEdited={onMaskEdited} onPendingChange={onMaskEditPending} />
                  ) : (
                    <span className="px-4 text-center text-sm text-text-tertiary">Preparing mask preview…</span>
                  )}
                </div>
              </>
            )}
            {currentMask && candidateOptions.length === 0 && (
              <div className="grid min-w-0 gap-1 [overflow-wrap:anywhere]">
                <p className="min-w-0 text-xs text-text-tertiary [overflow-wrap:anywhere]">{currentMask.width}×{currentMask.height}px PNG, {(currentMask.foregroundRatio * 100).toFixed(1)}% foreground. Black pixels become font ink.</p>
                <p className="min-w-0 text-xs text-text-secondary [overflow-wrap:anywhere]">Preview source: {describeMaskSource(currentMask)}.</p>
                {currentMask.warnings.length > 0 && (
                  <div className="min-w-0 rounded-md border border-orange-200 bg-amber-muted px-3 py-2 text-xs text-[#92400e] [overflow-wrap:anywhere]" role="status">
                    <strong className="font-semibold">Segmentation warning{currentMask.warnings.length > 1 ? 's' : ''}:</strong>
                    <ul className="mt-1 list-disc pl-4">{currentMask.warnings.map((warning) => <li key={warning}>{warning}</li>)}</ul>
                  </div>
                )}
              </div>
            )}
          </div>
        </div>
      )}

      <div className="flex flex-wrap items-center gap-2">
        <button type="button" onClick={onAccept} disabled={!currentMask || isProcessing || maskEditPending} className="primary-button">Accept {currentChar}</button>
        <button type="button" onClick={onRedo} disabled={!acceptedCurrent || isProcessing} className="secondary-button">Redo {currentChar}</button>
        <span className="text-xs text-text-tertiary">{acceptedCount}/{guidedCharacters.length} ready</span>
      </div>
      {maskEditPending && <p className="text-xs text-text-secondary" role="status">{maskEditError ?? 'Saving the current mask edit…'}</p>}

      {(guidedPreview || currentMask) && (
        <details className="group rounded-2xl border border-border bg-bg p-3">
          <summary className="cursor-pointer list-none text-sm font-semibold text-text-primary outline-none focus-visible:ring-2 focus-visible:ring-teal group-open:mb-3">
            Advanced correction tools
            <span className="sr-only">Refinement tools</span>
            <span className="ml-2 font-normal text-text-tertiary">{maskMethod === 'threshold' ? 'threshold' : 'segmentation'} · baseline {baseline.toFixed(2)}</span>
          </summary>
          <div className="grid gap-3">
            {candidateOptions.length > 0 && currentMask ? (
              <div className="grid gap-2 rounded-xl border border-border bg-surface p-3">
                <div>
                  <strong className="text-[13px] text-text-primary">Manual mask cleanup</strong>
                  <p className="mt-1 text-xs text-text-secondary">Only use this if none of the vector options are clean enough.</p>
                </div>
                <MaskCanvasEditor key={currentMask.url} mask={currentMask} currentChar={currentChar} baseline={baseline} onEdited={onMaskEdited} onPendingChange={onMaskEditPending} />
              </div>
            ) : null}
            <fieldset className="grid min-w-0 grid-cols-1 gap-2">
              <legend className="text-[13px] font-semibold text-text-primary">Preview method</legend>
              <label className="flex items-start gap-2 text-sm text-text-secondary">
                <input type="radio" name="mask-method" checked={maskMethod === 'threshold'} onChange={() => onMaskMethod('threshold')} />
                <span><strong className="text-text-primary">Threshold</strong><br />Fast local black/white extraction for dark ink or interior detail on a light background.</span>
              </label>
              <label className="flex items-start gap-2 text-sm text-text-secondary">
                <input type="radio" name="mask-method" checked={maskMethod === 'foreground'} onChange={() => onMaskMethod('foreground')} />
                <span><strong className="text-text-primary">Backend segmentation cutout</strong><br />Use the source photo, selected rectangle, method, and output style to request a real backend mask. No browser-only model is simulated.</span>
              </label>
            </fieldset>

            {maskMethod === 'threshold' ? (
              <div className="grid gap-3 rounded-xl border border-border bg-surface p-3">
                <fieldset className="grid min-w-0 grid-cols-1 gap-2">
                  <legend className="text-[13px] font-semibold text-text-primary">Ink detection</legend>
                  <label className="flex items-start gap-2 text-sm text-text-secondary">
                    <input type="radio" name="ink-mask-method" checked={inkMaskMethod === 'global'} onChange={() => onInkMaskMethod('global')} />
                    <span><strong className="text-text-primary">Global threshold</strong><br />Manual black/white cutoff. This remains the default.</span>
                  </label>
                  <label className="flex items-start gap-2 text-sm text-text-secondary">
                    <input type="radio" name="ink-mask-method" checked={inkMaskMethod === 'adaptive'} onChange={() => onInkMaskMethod('adaptive')} />
                    <span><strong className="text-text-primary">Adaptive local threshold</strong><br />May help with uneven paper lighting.</span>
                  </label>
                </fieldset>
                <label className="grid gap-1.5">
                  <span className="text-[13px] font-semibold text-text-primary">Threshold: {threshold}</span>
                  <input type="range" min="1" max="254" step="1" value={threshold} onChange={(e) => onThreshold(Number(e.target.value))} aria-label="Global threshold" disabled={inkMaskMethod === 'adaptive'} />
                </label>
                <label className="flex items-center gap-2 text-sm text-text-secondary">
                  <input type="checkbox" checked={invert} onChange={(e) => onInvert(e.target.checked)} />
                  Invert foreground (use when the object is lighter than the background)
                </label>
              </div>
            ) : (
              <ObjectRectangleControls
                method={foregroundMethod}
                style={foregroundStyle}
                rectangle={foregroundRectangle}
                inkThreshold={inkThreshold}
                onMethod={onForegroundMethod}
                onStyle={onForegroundStyle}
                onChange={onForegroundRectangle}
                onInkThreshold={onInkThreshold}
                onExtract={onExtractObject}
                disabled={!guidedPreview || isProcessing}
                status={foregroundStatus}
              />
            )}

            <label className="grid gap-1.5 rounded-xl border border-border bg-surface p-3">
              <span className="text-[13px] font-semibold text-text-primary">Baseline from top: {baseline.toFixed(2)}</span>
              <input type="range" min="0.05" max="0.95" step="0.01" value={baseline} onChange={(e) => onBaseline(Number(e.target.value))} />
            </label>
          </div>
        </details>
      )}

      <details className="group rounded-2xl border border-border bg-bg p-3" open>
        <summary className="cursor-pointer list-none text-sm font-semibold text-text-primary outline-none focus-visible:ring-2 focus-visible:ring-teal group-open:mb-3">
          Characters
          <span className="ml-2 font-normal text-text-tertiary">{acceptedCount} accepted · {missingCount} missing</span>
        </summary>
        <div className="grid grid-cols-8 gap-1 sm:grid-cols-12 md:grid-cols-16" aria-label="Guided character picker">
          {guidedCharacters.map((char) => {
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
      </details>
    </div>
  );
}


function CandidatePicker({ currentChar, candidates, selectedId, failures, status, error, objectsPending, onSelect }: {
  currentChar: string;
  candidates: CaptureCandidateOption[];
  selectedId: string | null;
  failures: { method: string; message: string; stage: 'ink' | 'objects' }[];
  status: string | null;
  error: string | null;
  objectsPending: boolean;
  onSelect: (candidate: CaptureCandidateOption) => void;
}) {
  return (
    <section className="grid min-w-0 gap-3" aria-label={`Letter options for ${currentChar}`} data-testid="candidate-picker">
      <div className="flex min-w-0 items-start justify-between gap-3">
        <div className="min-w-0">
          <span className="text-[13px] font-semibold text-text-primary">Choose the letter shape</span>
          <p className="mt-1 text-xs text-text-secondary">Smooth SVG previews are ready to compare. Accept the one that should become {currentChar}.</p>
        </div>
        {objectsPending ? <span className="shrink-0 rounded-full bg-teal-muted px-2.5 py-1 text-[11px] font-semibold text-teal" role="status">Trying object cutouts…</span> : null}
      </div>
      {status ? <p className="text-xs text-text-secondary" role="status">{status}</p> : null}
      {error ? <p className="rounded-lg border border-amber-muted bg-amber-muted px-3 py-2 text-xs text-[#7c4a03]" role="status">{error}</p> : null}
      <div className="grid min-w-0 gap-2 sm:grid-cols-2" role="listbox" aria-label="Extracted vector candidates">
        {candidates.map((candidate) => {
          const key = `${candidate.stage}:${candidate.id}`;
          const selected = selectedId === key;
          return (
            <button
              key={key}
              type="button"
              className={`candidate-card ${selected ? 'is-selected' : ''}`}
              role="option"
              aria-selected={selected}
              data-testid={`candidate-option-${candidate.stage}-${candidate.id}`}
              onClick={() => onSelect(candidate)}
            >
              <span className="candidate-card__preview"><img src={candidate.svgDataUrl} alt={`${candidate.label} vector preview for ${currentChar}`} /></span>
              <span className="candidate-card__copy">
                <strong>{candidate.label}</strong>
                <span>{candidate.stage === 'ink' ? 'Smooth letter outline' : 'Isolated object outline'} · SVG</span>
              </span>
              {selected ? <span className="candidate-card__badge"><CheckIcon /> Selected</span> : null}
              {candidate.warnings.length > 0 ? <span className="candidate-card__warning">{candidate.warnings[0]}</span> : null}
            </button>
          );
        })}
      </div>
      <div className="flex flex-wrap gap-2">
        {candidates.map((candidate) => (
          <a
            key={`${candidate.stage}:${candidate.id}:svg`}
            className="secondary-button"
            href={candidate.svgDataUrl}
            download={`${currentChar}-candidate-${candidate.id}.svg`}
          >
            Download {candidate.label} SVG
          </a>
        ))}
      </div>
      {failures.length > 0 ? (
        <details className="rounded-xl border border-border bg-bg px-3 py-2 text-xs text-text-secondary">
          <summary className="font-semibold text-text-primary">Methods that did not work ({failures.length})</summary>
          <ul className="mt-2 grid gap-1">
            {failures.map((failure, index) => <li key={`${failure.stage}-${failure.method}-${index}`}>{failure.stage}: {failure.method} — {failure.message}</li>)}
          </ul>
        </details>
      ) : null}
    </section>
  );
}


function PromptPointEditor({ preview, currentChar, points, promptMode, onPromptMode, onAddPoint, onClearPoints }: {
  preview: string;
  currentChar: string;
  points: CaptureForegroundPromptPoint[];
  promptMode: ForegroundPromptMode;
  onPromptMode: (mode: ForegroundPromptMode) => void;
  onAddPoint: (x: number, y: number) => void;
  onClearPoints: () => void;
}) {
  const frameRef = useRef<HTMLDivElement>(null);
  const imageRef = useRef<HTMLImageElement>(null);
  const [overlayBox, setOverlayBox] = useState<RectLike | null>(null);
  const positiveCount = points.filter((point) => point.label === 1).length;

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
    const image = imageRef.current;
    if (!image || points.length >= 16) return;
    updateOverlayBox();
    const [x, y] = normalizedPointInContainedImage(
      event.clientX,
      event.clientY,
      image.getBoundingClientRect(),
      image.naturalWidth || image.width,
      image.naturalHeight || image.height,
    );
    onAddPoint(x, y);
  }

  return (
    <div className="grid gap-2">
      <div
        ref={frameRef}
        className="relative overflow-hidden rounded-xl border border-border bg-bg-subtle"
        onClick={handleClick}
        role="button"
        tabIndex={0}
        aria-label={`Add ${promptMode === 'positive' ? 'Keep object' : 'Exclude background'} prompt point for ${currentChar}`}
        onKeyDown={(event) => {
          if (event.key !== 'Enter' && event.key !== ' ') return;
          event.preventDefault();
          onAddPoint(0.5, 0.5);
        }}
      >
        <img ref={imageRef} src={preview} alt={`Source photo for ${currentChar}`} className="h-[240px] w-full object-contain" onLoad={updateOverlayBox} />
        {overlayBox && (
          <svg
            className="pointer-events-none absolute"
            style={{ left: overlayBox.left, top: overlayBox.top, width: overlayBox.width, height: overlayBox.height }}
            viewBox="0 0 100 100"
            preserveAspectRatio="none"
            aria-hidden="true"
          >
            {points.map((point, index) => (
              <g key={`${point.x}-${point.y}-${point.label}-${index}`}>
                <circle cx={point.x * 100} cy={point.y * 100} r="2.3" fill={point.label === 1 ? '#16a34a' : '#dc2626'} stroke="white" strokeWidth="0.7" vectorEffect="non-scaling-stroke" />
                <text x={point.x * 100 + 2.8} y={point.y * 100 - 2.8} fontSize="5" fill={point.label === 1 ? '#14532d' : '#7f1d1d'}>{point.label === 1 ? '+' : '−'}</text>
              </g>
            ))}
          </svg>
        )}
      </div>
      <fieldset className="grid gap-2 rounded-lg border border-border bg-surface p-3">
        <legend className="text-xs font-semibold text-text-primary">Model prompt points</legend>
        <div className="flex flex-wrap gap-3">
          <label className="flex items-center gap-2 text-xs text-text-secondary">
            <input type="radio" name="foreground-prompt-mode" checked={promptMode === 'positive'} onChange={() => onPromptMode('positive')} />
            Keep object
          </label>
          <label className="flex items-center gap-2 text-xs text-text-secondary">
            <input type="radio" name="foreground-prompt-mode" checked={promptMode === 'negative'} onChange={() => onPromptMode('negative')} />
            Exclude background
          </label>
          <button type="button" onClick={onClearPoints} disabled={points.length === 0} className="secondary-button">Clear prompt points</button>
        </div>
        <p className="text-xs text-text-tertiary">
          Click/tap the source preview to add up to 16 normalized prompt points ({positiveCount} Keep object, {points.length - positiveCount} Exclude background). Model-only extraction requires at least one Keep object point.
        </p>
      </fieldset>
    </div>
  );
}

function MaskCanvasEditor({ mask, currentChar, baseline, onEdited, onPendingChange }: {
  mask: CurrentMask;
  currentChar: string;
  baseline: number;
  onEdited: (mask: MaskResult, sourceUrl: string) => void;
  onPendingChange: (pending: boolean, message?: string | null) => void;
}) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const undoStackRef = useRef<ImageData[]>([]);
  const paintingRef = useRef(false);
  const imageLoadSeq = useRef(0);
  const exportSeq = useRef(0);
  const [brushMode, setBrushMode] = useState<'add' | 'remove'>('add');
  const [brushSize, setBrushSize] = useState(18);
  const [ready, setReady] = useState(false);
  const [undoCount, setUndoCount] = useState(0);
  const [editStatus, setEditStatus] = useState<string | null>(null);

  const invalidatePendingCanvasWork = useCallback(() => {
    imageLoadSeq.current += 1;
    exportSeq.current += 1;
  }, []);

  const emitCurrentMask = useCallback(async () => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const requestId = ++exportSeq.current;
    const sourceUrl = mask.url;
    try {
      const next = await maskResultFromCanvas(canvas);
      if (requestId === exportSeq.current) onEdited(next, sourceUrl);
    } catch (err) {
      if (requestId !== exportSeq.current) return;
      const message = err instanceof Error ? err.message : 'Could not save the edited mask.';
      setEditStatus(message);
      onPendingChange(true, message);
    }
  }, [mask.url, onEdited, onPendingChange]);

  const drawMaskImage = useCallback((onDone?: () => void) => {
    const requestId = ++imageLoadSeq.current;
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext('2d', { willReadFrequently: true });
    if (!ctx) return;
    const image = new Image();
    image.decoding = 'async';
    image.onload = () => {
      if (requestId !== imageLoadSeq.current) return;
      canvas.width = mask.width;
      canvas.height = mask.height;
      ctx.drawImage(image, 0, 0, mask.width, mask.height);
      setReady(true);
      onDone?.();
    };
    image.onerror = () => {
      if (requestId !== imageLoadSeq.current) return;
      const message = 'Could not load this mask for manual editing.';
      setReady(false);
      setEditStatus(message);
      onPendingChange(true, message);
    };
    image.src = mask.url;
  }, [mask.height, mask.url, mask.width, onPendingChange]);

  useEffect(() => {
    undoStackRef.current = [];
    invalidatePendingCanvasWork();
    drawMaskImage();
    return invalidatePendingCanvasWork;
  }, [drawMaskImage, invalidatePendingCanvasWork]);

  function pushUndoSnapshot() {
    const canvas = canvasRef.current;
    const ctx = canvas?.getContext('2d', { willReadFrequently: true });
    if (!canvas || !ctx || canvas.width <= 0 || canvas.height <= 0) return;
    undoStackRef.current = [...undoStackRef.current.slice(-19), ctx.getImageData(0, 0, canvas.width, canvas.height)];
    setUndoCount(undoStackRef.current.length);
  }

  function restoreSnapshot(snapshot: ImageData, status: string) {
    const canvas = canvasRef.current;
    const ctx = canvas?.getContext('2d', { willReadFrequently: true });
    if (!canvas || !ctx) return;
    ctx.putImageData(snapshot, 0, 0);
    setEditStatus(status);
    void emitCurrentMask();
  }

  function paintAt(clientX: number, clientY: number) {
    const canvas = canvasRef.current;
    const ctx = canvas?.getContext('2d', { willReadFrequently: true });
    if (!canvas || !ctx || canvas.width <= 0 || canvas.height <= 0) return;
    const [cx, cy] = maskCanvasPointFromClient(clientX, clientY, canvas.getBoundingClientRect(), canvas.width, canvas.height);
    const radius = Math.max(1, Math.round(brushSize / 2));
    const data = ctx.getImageData(0, 0, canvas.width, canvas.height);
    const value = brushMode === 'add' ? 0 : 255;
    const minX = Math.max(0, cx - radius);
    const maxX = Math.min(canvas.width - 1, cx + radius);
    const minY = Math.max(0, cy - radius);
    const maxY = Math.min(canvas.height - 1, cy + radius);
    for (let y = minY; y <= maxY; y++) {
      for (let x = minX; x <= maxX; x++) {
        const dx = x - cx;
        const dy = y - cy;
        if (dx * dx + dy * dy > radius * radius) continue;
        const index = (y * canvas.width + x) * 4;
        data.data[index] = value;
        data.data[index + 1] = value;
        data.data[index + 2] = value;
        data.data[index + 3] = 255;
      }
    }
    ctx.putImageData(data, 0, 0);
  }

  async function undoEdit() {
    const canvas = canvasRef.current;
    const ctx = canvas?.getContext('2d', { willReadFrequently: true });
    const previous = undoStackRef.current.pop();
    if (!canvas || !ctx || !previous) return;
    onPendingChange(true);
    ctx.putImageData(previous, 0, 0);
    setUndoCount(undoStackRef.current.length);
    setEditStatus('Undid the last brush stroke.');
    await emitCurrentMask();
  }

  function resetEdits() {
    exportSeq.current++;
    undoStackRef.current = [];
    setUndoCount(0);
    setReady(false);
    onPendingChange(true);
    drawMaskImage(() => {
      setEditStatus('Reset to the latest extracted mask.');
      void emitCurrentMask();
    });
  }

  return (
    <div data-mask-editor className="grid min-w-0 w-full max-w-full grid-cols-1 gap-3 overflow-hidden p-3">
      <div className="relative mx-auto w-full max-w-[220px]">
        <canvas
          ref={canvasRef}
          width={mask.width}
          height={mask.height}
          className="block h-auto w-full touch-none border border-border [image-rendering:auto]"
          role="img"
          aria-label={`Editable mask for ${currentChar}`}
          onPointerDown={(event) => {
            if ((event.button ?? 0) > 0 || !ready) return;
            onPendingChange(true);
            paintingRef.current = true;
            setEditStatus(null);
            exportSeq.current++;
            event.currentTarget.setPointerCapture?.(event.pointerId);
            pushUndoSnapshot();
            paintAt(event.clientX, event.clientY);
          }}
          onPointerMove={(event) => {
            if (!paintingRef.current || !ready) return;
            paintAt(event.clientX, event.clientY);
          }}
          onPointerUp={(event) => {
            if (!paintingRef.current) return;
            paintingRef.current = false;
            event.currentTarget.releasePointerCapture?.(event.pointerId);
            void emitCurrentMask();
          }}
          onPointerCancel={() => {
            if (paintingRef.current) {
              const previous = undoStackRef.current.pop();
              if (previous) {
                setUndoCount(undoStackRef.current.length);
                restoreSnapshot(previous, 'Cancelled the brush stroke.');
              } else {
                onPendingChange(false);
              }
            } else {
              onPendingChange(false);
            }
            paintingRef.current = false;
          }}
        />
        <div className="pointer-events-none absolute inset-x-0 border-t-2 border-dashed border-teal" style={{ top: `${baseline * 100}%` }} aria-hidden="true" />
      </div>
      <div className="grid min-w-0 gap-2 rounded-lg border border-border bg-surface p-3">
        <fieldset className="flex min-w-0 flex-wrap gap-3">
          <legend className="sr-only">Mask brush mode</legend>
          <label className="flex items-center gap-2 text-xs text-text-secondary">
            <input type="radio" name="mask-brush-mode" checked={brushMode === 'add'} onChange={() => setBrushMode('add')} />
            Add black ink
          </label>
          <label className="flex items-center gap-2 text-xs text-text-secondary">
            <input type="radio" name="mask-brush-mode" checked={brushMode === 'remove'} onChange={() => setBrushMode('remove')} />
            Remove to white
          </label>
        </fieldset>
        <label className="grid min-w-0 gap-1 text-xs font-semibold text-text-secondary">
          Brush size: {brushSize}px
          <input className="min-w-0 w-full" type="range" min="2" max="80" step="1" value={brushSize} onChange={(e) => setBrushSize(Number(e.target.value))} />
        </label>
        <div className="flex flex-wrap gap-2">
          <button type="button" onClick={undoEdit} disabled={!ready || undoCount < 1} className="secondary-button">Undo mask edit</button>
          <button type="button" onClick={resetEdits} disabled={!ready} className="secondary-button">Reset mask edits</button>
        </div>
        <p className="text-xs text-text-tertiary">Brush edits only add or remove pixels in this mask PNG. They do not crop to a bounding box or delete disconnected parts.</p>
        {editStatus && <p className="text-xs text-text-secondary" role="status">{editStatus}</p>}
      </div>
    </div>
  );
}

function ObjectRectangleControls({ method, style, rectangle, inkThreshold, onMethod, onStyle, onChange, onInkThreshold, onExtract, disabled, status }: {
  method: CaptureForegroundRequestMethod;
  style: CaptureForegroundStyle;
  rectangle: NormalizedRectangle;
  inkThreshold: number;
  onMethod: (method: CaptureForegroundRequestMethod) => void;
  onStyle: (style: CaptureForegroundStyle) => void;
  onChange: (rectangle: NormalizedRectangle) => void;
  onInkThreshold: (value: number) => void;
  onExtract: () => void;
  disabled: boolean;
  status: string | null;
}) {
  const labels = ['Left', 'Top', 'Right', 'Bottom'] as const;
  return (
    <div className="grid gap-3 rounded-lg border border-border bg-surface p-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="text-xs text-text-secondary">Place the rectangle around the foreground object. The worker returns a real mask from the original source photo. Auto may use a model when available or honestly fall back to classical segmentation with a warning.</p>
        <button type="button" onClick={onExtract} disabled={disabled} className="secondary-button">Extract mask</button>
      </div>
      <fieldset className="grid min-w-0 grid-cols-1 gap-2">
        <legend className="text-xs font-semibold text-text-primary">Segmentation method</legend>
        <label className="flex items-start gap-2 text-sm text-text-secondary">
          <input type="radio" name="foreground-method" checked={method === 'auto'} onChange={() => onMethod('auto')} />
          <span><strong className="text-text-primary">Auto</strong><br />No Keep object point uses GrabCut. With a Keep object point, request SlimSAM; unavailable model fallbacks must be reported as warnings.</span>
        </label>
        <label className="flex items-start gap-2 text-sm text-text-secondary">
          <input type="radio" name="foreground-method" checked={method === 'model'} onChange={() => onMethod('model')} />
          <span><strong className="text-text-primary">SlimSAM point cutout</strong><br />Require point-prompted SlimSAM segmentation; add at least one Keep object point or the request is blocked.</span>
        </label>
        <label className="flex items-start gap-2 text-sm text-text-secondary">
          <input type="radio" name="foreground-method" checked={method === 'box-model'} onChange={() => onMethod('box-model')} />
          <span><strong className="text-text-primary">AI box cutout (EfficientSAM)</strong><br />Use the rectangle as the EfficientSAM box prompt. Keep/exclude points are retained for SlimSAM but not sent for this mode.</span>
        </label>
        <label className="flex items-start gap-2 text-sm text-text-secondary">
          <input type="radio" name="foreground-method" checked={method === 'grabcut'} onChange={() => onMethod('grabcut')} />
          <span><strong className="text-text-primary">Classical GrabCut</strong><br />Use the rectangle-guided classical segmentation path.</span>
        </label>
      </fieldset>
      <fieldset className="grid min-w-0 grid-cols-1 gap-2">
        <legend className="text-xs font-semibold text-text-primary">Mask style</legend>
        <label className="flex items-start gap-2 text-sm text-text-secondary">
          <input type="radio" name="foreground-style" checked={style === 'silhouette'} onChange={() => onStyle('silhouette')} />
          <span><strong className="text-text-primary">Silhouette</strong><br />Return the segmented foreground shape as solid black on white.</span>
        </label>
        <label className="flex items-start gap-2 text-sm text-text-secondary">
          <input type="radio" name="foreground-style" checked={style === 'ink'} onChange={() => onStyle('ink')} />
          <span><strong className="text-text-primary">Interior ink</strong><br />Keep dark interior strokes within the segmented foreground using a worker-side threshold.</span>
        </label>
      </fieldset>
      {style === 'ink' && (
        <label className="grid min-w-0 gap-1.5">
          <span className="text-[13px] font-semibold text-text-primary">Interior ink threshold: {inkThreshold}</span>
          <input className="min-w-0 w-full" type="range" min="1" max="254" step="1" value={inkThreshold} onChange={(e) => onInkThreshold(Number(e.target.value))} />
        </label>
      )}
      <div className="grid min-w-0 gap-2 sm:grid-cols-4">
        {rectangle.map((value, index) => (
          <label key={labels[index]} className="grid min-w-0 gap-1 text-xs font-semibold text-text-secondary">
            {labels[index]} {value.toFixed(2)}
            <input
              aria-label={`${labels[index]} boundary slider`}
              className="min-w-0 w-full"
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
              aria-label={`${labels[index]} boundary`}
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

function StatusPanel({ state, job, acceptedCharacters, allowDelete, onDeleted }: { state: LocalState; job: JobResponse | null; acceptedCharacters: string[] | null; allowDelete: boolean; onDeleted: () => void }) {
  const [deletedJobId, setDeletedJobId] = useState<string | null>(null);
  if (job && deletedJobId === job.jobId) return (
    <aside className="studio-result-panel rounded-[22px] border border-border bg-surface p-5 text-sm text-text-secondary" role="status">
      Job access removed. File cleanup is queued; accepted glyphs in this tab remain available for editing. Another build will upload fresh inputs.
    </aside>
  );
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
    <aside className="studio-result-panel grid min-w-0 content-start gap-4 rounded-[22px] border border-border bg-surface p-5" aria-live="polite">
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
        <p className="text-[13px] text-text-tertiary">Your font preview will appear here. Add a character and build your font.</p>
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
            <a key={artifact.kind} className="flex items-center justify-between rounded-lg border border-border bg-bg px-4 py-3 text-[13px] font-semibold transition-colors hover:border-border-strong" href={artifact.url} download onClick={() => recordFunnelEvent('font_download_requested' as Parameters<typeof recordFunnelEvent>[0])}>
              <span>{artifact.label}</span>
              <span className="font-mono text-[11px] font-normal text-text-tertiary">{artifact.kind.toUpperCase()}</span>
            </a>
          ))}
          <a className="mt-2 text-sm font-semibold text-teal" href="/help/install-fonts">How to install in Word or PowerPoint →</a>
        </div>
      )}

      {isSuccess && job && <GeneratedProof key={`proof-${job.jobId}`} job={job} acceptedCharacters={acceptedCharacters} />}

      {allowDelete && job && (job.status === 'succeeded' || job.status === 'failed') && <DeleteJobButton key={`delete-${job.jobId}`} jobId={job.jobId} onDeleted={(id) => { setDeletedJobId(id); onDeleted(); }} />}
      {job && <small className="text-xs text-text-tertiary">This job is retained until {new Date(job.retentionExpiresAt).toLocaleString()}.</small>}
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
