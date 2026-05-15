'use client';

import { FormEvent, useCallback, useEffect, useRef, useState } from 'react';
import {
  ERROR_COPY,
  isSafeFontName,
  isSupportedImage,
  MAX_UPLOAD_BYTES,
  type JobResponse,
  type JobStage,
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

const POLL_INTERVAL_MS = 2000;
const MAX_POLLS = 120;

const PIPELINE_STAGES: { key: JobStage; label: string }[] = [
  { key: 'marker_detection', label: 'Finding page markers' },
  { key: 'homography_rectification', label: 'Correcting perspective' },
  { key: 'glyph_extraction', label: 'Extracting glyph cells' },
  { key: 'font_generation', label: 'Generating font outlines' },
  { key: 'font_validation', label: 'Validating font files' },
  { key: 'artifact_publish', label: 'Publishing downloads' },
];

function stageIndex(stage: string): number {
  return PIPELINE_STAGES.findIndex((s) => s.key === stage);
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

export function UploadWorkbench() {
  const [file, setFile] = useState<File | null>(null);
  const [preview, setPreview] = useState<string | null>(null);
  const [fontName, setFontName] = useState('MyHandwrite-Regular');
  const [familyName, setFamilyName] = useState('My Handwrite');
  const [styleName, setStyleName] = useState('Regular');
  const [state, setState] = useState<LocalState>('idle');
  const [job, setJob] = useState<JobResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [dragover, setDragover] = useState(false);
  const pollRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const pollCount = useRef(0);
  const cameraRef = useRef<HTMLInputElement>(null);
  const fileRef = useRef<HTMLInputElement>(null);

  const clearPolling = useCallback(() => {
    if (pollRef.current) clearTimeout(pollRef.current);
    pollRef.current = null;
    pollCount.current = 0;
  }, []);

  useEffect(() => () => clearPolling(), [clearPolling]);

  function handleFile(f: File | null) {
    if (preview) URL.revokeObjectURL(preview);
    setFile(f);
    setPreview(f ? URL.createObjectURL(f) : null);
    setError(null);
    if (state === 'failed' || state === 'succeeded') {
      setState('idle');
      setJob(null);
    }
  }

  function removeFile() {
    handleFile(null);
  }

  async function pollJob(jobId: string) {
    if (pollCount.current >= MAX_POLLS) {
      setState('failed');
      setError('Job is taking too long. Check backend logs.');
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

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError(null);
    setJob(null);
    clearPolling();

    if (!file) return setError('Choose a photographed template image first.');
    if (!isSupportedImage(file.type)) return setError(ERROR_COPY.UNSUPPORTED_IMAGE_TYPE);
    if (file.size > MAX_UPLOAD_BYTES) return setError(ERROR_COPY.UPLOAD_OBJECT_TOO_LARGE);
    if (!isSafeFontName(fontName)) return setError(ERROR_COPY.FONT_METADATA_INVALID);

    try {
      setState('preparing_upload');
      const uploadRes = await fetch('/api/uploads', {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({ filename: file.name, contentType: file.type, sizeBytes: file.size }),
      });
      const uploadPayload = (await uploadRes.json()) as UploadResponse | { error?: { message?: string } };
      if (!uploadRes.ok || !('uploadUrl' in uploadPayload)) {
        setState('failed');
        return setError(('error' in uploadPayload ? uploadPayload.error?.message : undefined) ?? 'Could not prepare the upload.');
      }

      if (uploadPayload.mode === 'live' || uploadPayload.mode === 'local') {
        setState('uploading');
        const put = await fetch(uploadPayload.uploadUrl, {
          method: uploadPayload.method,
          body: file,
          headers: { 'content-type': file.type },
        });
        if (!put.ok) {
          setState('failed');
          return setError('The upload failed. Try again with a smaller or sharper image.');
        }
      }

      setState('creating_job');
      const createRes = await fetch('/api/jobs', {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({
          inputPhoto: { objectKey: uploadPayload.objectKey, bucket: uploadPayload.bucket, contentType: file.type, sizeBytes: file.size },
          font: { fontName, familyName, styleName },
          template: { version: 'v1' },
        }),
      });
      const created = (await createRes.json()) as JobResponse | { error?: { message?: string } };
      if (!createRes.ok || !('jobId' in created)) {
        setState('failed');
        return setError(('error' in created ? created.error?.message : undefined) ?? 'Could not create the font job.');
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
    } catch (err) {
      setState('failed');
      setError(err instanceof Error ? err.message : 'An unexpected error occurred.');
    }
  }

  const isProcessing = state === 'preparing_upload' || state === 'uploading' || state === 'creating_job' || state === 'polling';

  return (
    <section className="grid grid-cols-1 items-start gap-6 md:grid-cols-[1.2fr_1fr]" aria-labelledby="workbench-title">
      <div className="col-span-full mb-2">
        <span className="inline-block rounded-[4px] bg-teal-muted px-2.5 py-1 font-mono text-[11px] font-medium uppercase tracking-[.12em] text-teal mb-3">
          Build
        </span>
        <h2 id="workbench-title" className="text-[clamp(1.8rem,3.5vw,2.8rem)] font-bold tracking-[-0.04em] leading-none mt-1">
          Upload a finished sheet
        </h2>
        <p className="mt-2 text-sm text-text-secondary">
          Photograph your completed template and upload it here. The backend detects markers,
          corrects perspective, extracts glyphs, and generates installable font files.
        </p>
      </div>

      <form className="grid gap-5 rounded-[22px] border border-border bg-surface p-7" onSubmit={submit}>
        {file && preview ? (
          <div className="relative overflow-hidden rounded-xl border border-border">
            <img src={preview} alt="Captured template preview" className="h-[180px] w-full object-cover" />
            <div className="absolute inset-0 flex items-end bg-gradient-to-t from-black/50 via-transparent p-3">
              <span className="text-xs font-medium text-white">{file.name} &middot; {(file.size / 1024 / 1024).toFixed(1)} MB</span>
            </div>
            <button
              type="button"
              onClick={removeFile}
              aria-label="Remove photo"
              className="absolute top-2 right-2 flex h-7 w-7 items-center justify-center rounded-full bg-black/60 text-white transition-colors hover:bg-black/80"
            >
              <XIcon />
            </button>
          </div>
        ) : (
          <div
            className={`relative flex flex-col items-center justify-center gap-3 rounded-xl border-2 border-dashed px-6 py-6 transition-all duration-200 ${
              dragover ? 'border-teal bg-teal-muted' : 'border-border bg-bg hover:border-teal hover:bg-teal-muted'
            }`}
            onDragOver={(e) => { e.preventDefault(); setDragover(true); }}
            onDragLeave={() => setDragover(false)}
            onDrop={(e) => { e.preventDefault(); setDragover(false); handleFile(e.dataTransfer.files[0] ?? null); }}
          >
            <div className="flex gap-3">
              <button
                type="button"
                onClick={() => cameraRef.current?.click()}
                className="flex h-12 items-center gap-2 rounded-lg border border-border bg-surface px-4 text-sm font-medium text-text-primary transition-all duration-150 hover:border-border-strong hover:shadow-[0_1px_2px_rgba(0,0,0,.04)] active:scale-[0.98]"
              >
                <CameraIcon className="text-teal" />
                Take photo
              </button>
              <button
                type="button"
                onClick={() => fileRef.current?.click()}
                className="flex h-12 items-center gap-2 rounded-lg border border-border bg-surface px-4 text-sm font-medium text-text-primary transition-all duration-150 hover:border-border-strong hover:shadow-[0_1px_2px_rgba(0,0,0,.04)] active:scale-[0.98]"
              >
                <UploadIcon className="text-text-secondary" />
                Upload file
              </button>
            </div>
            <p className="text-center text-xs text-text-tertiary">
              or drag and drop &middot; JPEG, PNG, WebP &middot; up to {Math.round(MAX_UPLOAD_BYTES / 1024 / 1024)} MB
            </p>
            <input
              ref={cameraRef}
              type="file"
              accept="image/jpeg,image/png,image/webp"
              capture="environment"
              className="hidden"
              onChange={(e) => handleFile(e.target.files?.[0] ?? null)}
            />
            <input
              ref={fileRef}
              type="file"
              accept="image/jpeg,image/png,image/webp"
              className="hidden"
              onChange={(e) => handleFile(e.target.files?.[0] ?? null)}
            />
          </div>
        )}

        <div className="grid grid-cols-1 gap-3.5 sm:grid-cols-2">
          <label className="col-span-full grid gap-1.5">
            <span className="text-[13px] font-semibold text-text-primary">Font name</span>
            <input
              type="text"
              value={fontName}
              onChange={(e) => setFontName(e.target.value)}
              className="h-[42px] rounded-lg border border-border bg-bg px-3.5 text-sm outline-none transition-colors focus:border-accent"
            />
          </label>
          <label className="grid gap-1.5">
            <span className="text-[13px] font-semibold text-text-primary">Family name</span>
            <input
              type="text"
              value={familyName}
              onChange={(e) => setFamilyName(e.target.value)}
              className="h-[42px] rounded-lg border border-border bg-bg px-3.5 text-sm outline-none transition-colors focus:border-accent"
            />
          </label>
          <label className="grid gap-1.5">
            <span className="text-[13px] font-semibold text-text-primary">Style</span>
            <input
              type="text"
              value={styleName}
              onChange={(e) => setStyleName(e.target.value)}
              className="h-[42px] rounded-lg border border-border bg-bg px-3.5 text-sm outline-none transition-colors focus:border-accent"
            />
          </label>
        </div>

        {error && (
          <p className="rounded-lg bg-red-muted px-3.5 py-2.5 text-[13px] text-red" role="alert">{error}</p>
        )}

        <button
          type="submit"
          disabled={isProcessing || !file}
          className="h-11 w-full rounded-full border border-accent bg-accent text-sm font-semibold text-white transition-all duration-150 hover:bg-accent-hover active:scale-[0.98] active:translate-y-px disabled:border-border disabled:bg-bg-subtle disabled:text-text-tertiary"
        >
          {isProcessing ? 'Processing…' : 'Build font'}
        </button>
      </form>

      <StatusPanel state={state} job={job} />
    </section>
  );
}

function StatusPanel({ state, job }: { state: LocalState; job: JobResponse | null }) {
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
        <p className="text-[13px] text-text-tertiary">
          Upload a photographed template to start a font build.
        </p>
      )}

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
            <p key={`${w.code}-${w.glyph}`} className="mt-0.5 text-[13px] text-[#92400e]">
              {w.glyph ? `${w.glyph}: ` : ''}{w.message}
            </p>
          ))}
        </div>
      )}

      {job?.artifacts && job.artifacts.length > 0 && (
        <div className="grid gap-2">
          <strong className="mb-1 text-[13px] text-text-secondary">Downloads</strong>
          {job.artifacts.map((artifact) => (
            <a
              key={artifact.kind}
              className="flex items-center justify-between rounded-lg border border-border bg-bg px-4 py-3 text-[13px] font-semibold transition-colors hover:border-border-strong"
              href={artifact.url}
              download
            >
              <span>{artifact.label}</span>
              <span className="font-mono text-[11px] font-normal text-text-tertiary">{artifact.kind.toUpperCase()}</span>
            </a>
          ))}
        </div>
      )}

      <small className="text-xs text-text-tertiary">
        {job
          ? `Files expire ${new Date(job.retentionExpiresAt).toLocaleString()}`
          : 'Generated fonts are retained for 24 hours.'}
      </small>
    </aside>
  );
}
