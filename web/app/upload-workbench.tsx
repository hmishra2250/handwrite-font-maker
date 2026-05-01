'use client';

import { FormEvent, useMemo, useState } from 'react';
import { ERROR_COPY, isSafeFontName, isSupportedImage, MAX_UPLOAD_BYTES, type JobResponse, type UploadResponse } from '@/lib/contracts';

type LocalState = 'idle' | 'preparing_upload' | 'uploading' | 'creating_job' | 'queued' | 'running' | 'succeeded' | 'failed' | 'expired';

const demoNotice = 'Demo mode uses sample artifacts until Render and Supabase environment variables are configured.';

export function UploadWorkbench() {
  const [file, setFile] = useState<File | null>(null);
  const [fontName, setFontName] = useState('MyHandwrite-Regular');
  const [familyName, setFamilyName] = useState('My Handwrite');
  const [styleName, setStyleName] = useState('Regular');
  const [state, setState] = useState<LocalState>('idle');
  const [job, setJob] = useState<JobResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  const fileHelp = useMemo(() => {
    if (!file) return `JPEG, PNG, or WebP up to ${Math.round(MAX_UPLOAD_BYTES / 1024 / 1024)} MB.`;
    return `${file.name} · ${(file.size / 1024 / 1024).toFixed(2)} MB`;
  }, [file]);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError(null);
    setJob(null);

    if (!file) return setError('Choose a photographed template image first.');
    if (!isSupportedImage(file.type)) return setError(ERROR_COPY.UNSUPPORTED_IMAGE_TYPE);
    if (file.size > MAX_UPLOAD_BYTES) return setError(ERROR_COPY.UPLOAD_OBJECT_TOO_LARGE);
    if (!isSafeFontName(fontName)) return setError(ERROR_COPY.FONT_METADATA_INVALID);

    setState('preparing_upload');
    const uploadResponse = await fetch('/api/uploads', {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ filename: file.name, contentType: file.type, sizeBytes: file.size })
    });
    const uploadPayload = (await uploadResponse.json()) as UploadResponse | { error?: { message?: string } };
    if (!uploadResponse.ok || !('uploadUrl' in uploadPayload)) {
      setState('failed');
      return setError(('error' in uploadPayload ? uploadPayload.error?.message : undefined) ?? 'Could not prepare the upload.');
    }

    if (uploadPayload.mode === 'live') {
      setState('uploading');
      const put = await fetch(uploadPayload.uploadUrl, { method: uploadPayload.method, body: file, headers: { 'content-type': file.type } });
      if (!put.ok) {
        setState('failed');
        return setError('The signed upload failed. Try again with a smaller or sharper image.');
      }
    }

    setState('creating_job');
    const createResponse = await fetch('/api/jobs', {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({
        inputPhoto: { objectKey: uploadPayload.objectKey, bucket: uploadPayload.bucket, contentType: file.type, sizeBytes: file.size },
        font: { fontName, familyName, styleName },
        template: { version: 'v1' }
      })
    });
    const created = (await createResponse.json()) as JobResponse | { error?: { message?: string } };
    if (!createResponse.ok || !('jobId' in created)) {
      setState('failed');
      return setError(('error' in created ? created.error?.message : undefined) ?? 'Could not create the font job.');
    }

    setState(created.status === 'queued' ? 'queued' : created.status);
    setJob(created);

    const statusResponse = await fetch(`/api/jobs/${encodeURIComponent(created.jobId)}`, { cache: 'no-store' });
    if (statusResponse.ok) {
      const latest = (await statusResponse.json()) as JobResponse;
      setJob(latest);
      setState(latest.status);
    }
  }

  return (
    <section className="workbench" aria-labelledby="workbench-title">
      <div className="workbenchIntro">
        <p className="eyebrow">Build test bench</p>
        <h2 id="workbench-title">Upload a finished sheet</h2>
        <p>{demoNotice}</p>
      </div>
      <form className="uploadForm" onSubmit={submit}>
        <label>
          <span>Completed template photo</span>
          <input type="file" accept="image/jpeg,image/png,image/webp" capture="environment" onChange={(event) => setFile(event.target.files?.[0] ?? null)} />
          <small>{fileHelp}</small>
        </label>
        <div className="fieldGrid">
          <label><span>Font name</span><input value={fontName} onChange={(e) => setFontName(e.target.value)} /></label>
          <label><span>Family name</span><input value={familyName} onChange={(e) => setFamilyName(e.target.value)} /></label>
          <label><span>Style</span><input value={styleName} onChange={(e) => setStyleName(e.target.value)} /></label>
        </div>
        {error ? <p className="errorText" role="alert">{error}</p> : null}
        <button type="submit" disabled={state !== 'idle' && state !== 'failed' && state !== 'succeeded'}>Start font build</button>
      </form>
      <StatusPanel state={state} job={job} />
    </section>
  );
}

function StatusPanel({ state, job }: { state: LocalState; job: JobResponse | null }) {
  return (
    <aside className="statusPanel" aria-live="polite">
      <div className="statusHeader"><span>Status</span><strong>{job?.status ?? state}</strong></div>
      <p>{job?.progressLabel ?? 'Waiting for a photographed template.'}</p>
      {job?.error ? <div className="errorBox"><strong>{job.error.code}</strong><p>{job.error.message}</p></div> : null}
      {job?.warnings.length ? <div className="warningBox"><strong>Warnings</strong>{job.warnings.map((w) => <p key={`${w.code}-${w.glyph}`}>{w.message}</p>)}</div> : null}
      {job?.artifacts.length ? <div className="artifactList"><strong>Downloads</strong>{job.artifacts.map((artifact) => <a key={artifact.kind} href={artifact.url} download>{artifact.label}</a>)}</div> : null}
      <small>Files expire after {job ? new Date(job.retentionExpiresAt).toLocaleString() : 'the configured retention window'}.</small>
    </aside>
  );
}
