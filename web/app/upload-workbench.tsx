'use client';

import { FormEvent, useCallback, useEffect, useRef, useState } from 'react';
import {
  ERROR_COPY,
  isSafeFontName,
  isSupportedImage,
  JOB_STAGES,
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
    <section className="workbench" aria-labelledby="workbench-title">
      <div className="workbenchIntro">
        <span className="eyebrow">Build</span>
        <h2 id="workbench-title">Upload a finished sheet</h2>
        <p>
          Photograph your completed template and upload it here. The backend detects markers,
          corrects perspective, extracts glyphs, and generates installable font files.
        </p>
      </div>

      <form className="uploadForm" onSubmit={submit}>
        {file && preview ? (
          <div className="imagePreview">
            <img src={preview} alt="Captured template preview" />
            <div className="previewOverlay">
              <span className="previewMeta">{file.name} &middot; {(file.size / 1024 / 1024).toFixed(1)} MB</span>
            </div>
            <button type="button" className="previewRemove" onClick={removeFile} aria-label="Remove photo">&times;</button>
          </div>
        ) : (
          <div
            className={`captureZone ${dragover ? 'dragover' : ''}`}
            onDragOver={(e) => { e.preventDefault(); setDragover(true); }}
            onDragLeave={() => setDragover(false)}
            onDrop={(e) => { e.preventDefault(); setDragover(false); handleFile(e.dataTransfer.files[0] ?? null); }}
          >
            <div className="captureZoneIcon">
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <path d="M23 19a2 2 0 0 1-2 2H3a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h4l2-3h6l2 3h4a2 2 0 0 1 2 2z" />
                <circle cx="12" cy="13" r="4" />
              </svg>
            </div>
            <div className="captureZoneText">
              <strong>Take a photo or drag an image</strong>
              JPEG, PNG, or WebP &middot; up to {Math.round(MAX_UPLOAD_BYTES / 1024 / 1024)} MB
            </div>
            <input
              type="file"
              accept="image/jpeg,image/png,image/webp"
              capture="environment"
              onChange={(e) => handleFile(e.target.files?.[0] ?? null)}
            />
          </div>
        )}

        <div className="fieldGrid">
          <label>
            <span>Font name</span>
            <input type="text" value={fontName} onChange={(e) => setFontName(e.target.value)} />
          </label>
          <label>
            <span>Family name</span>
            <input type="text" value={familyName} onChange={(e) => setFamilyName(e.target.value)} />
          </label>
          <label>
            <span>Style</span>
            <input type="text" value={styleName} onChange={(e) => setStyleName(e.target.value)} />
          </label>
        </div>

        {error && <p className="errorText" role="alert">{error}</p>}

        <button type="submit" className="submitBtn" disabled={isProcessing || !file}>
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

  const badgeClass = isFailed ? 'failed' : isSuccess ? 'succeeded' : isActive ? 'running' : 'idle';
  const badgeLabel = isFailed ? 'Failed' : isSuccess ? 'Complete' : isActive ? 'Processing' : 'Ready';

  return (
    <aside className="statusPanel" aria-live="polite">
      <div className="statusHeader">
        <span>Status</span>
        <span className={`statusBadge ${badgeClass}`}>{badgeLabel}</span>
      </div>

      {(isActive || isSuccess || isFailed) && (
        <div className="progressStages">
          {PIPELINE_STAGES.map((stage, idx) => {
            let dotClass = '';
            let labelClass = '';
            if (isFailed && idx === currentIdx) {
              dotClass = 'error';
              labelClass = 'active';
            } else if (idx < currentIdx || isSuccess) {
              dotClass = 'done';
              labelClass = 'done';
            } else if (idx === currentIdx && isActive) {
              dotClass = 'active';
              labelClass = 'active';
            }
            return (
              <div key={stage.key} className="progressStage">
                <div className={`progressDot ${dotClass}`}>
                  {dotClass === 'done' ? '✓' : dotClass === 'error' ? '!' : ''}
                </div>
                <span className={`progressLabel ${labelClass}`}>{stage.label}</span>
              </div>
            );
          })}
        </div>
      )}

      {!isActive && !isSuccess && !isFailed && (
        <p style={{ fontSize: '13px', color: 'var(--text-tertiary)' }}>
          Upload a photographed template to start a font build.
        </p>
      )}

      {job?.error && (
        <div className="errorBox">
          <strong>{job.error.code}</strong>
          <p>{job.error.message}</p>
        </div>
      )}

      {job?.warnings && job.warnings.length > 0 && (
        <div className="warningBox">
          <strong>{job.warnings.length} warning{job.warnings.length > 1 ? 's' : ''}</strong>
          {job.warnings.map((w) => (
            <p key={`${w.code}-${w.glyph}`}>{w.glyph ? `${w.glyph}: ` : ''}{w.message}</p>
          ))}
        </div>
      )}

      {job?.artifacts && job.artifacts.length > 0 && (
        <div className="artifactList">
          <strong>Downloads</strong>
          {job.artifacts.map((artifact) => (
            <a key={artifact.kind} className="artifactCard" href={artifact.url} download>
              <span>{artifact.label}</span>
              <span className="artifactMeta">{artifact.kind.toUpperCase()}</span>
            </a>
          ))}
        </div>
      )}

      <small>
        {job
          ? `Files expire ${new Date(job.retentionExpiresAt).toLocaleString()}`
          : 'Generated fonts are retained for 24 hours.'}
      </small>
    </aside>
  );
}
