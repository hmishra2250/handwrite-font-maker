'use client';

import { useState } from 'react';

export function DeleteJobButton({ jobId, onDeleted }: { jobId: string; onDeleted: (jobId: string) => void }) {
  const [confirming, setConfirming] = useState(false);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function remove() {
    setPending(true);
    setError(null);
    try {
      const response = await fetch(`/api/jobs/${encodeURIComponent(jobId)}`, { method: 'DELETE', credentials: 'same-origin' });
      if (!response.ok) throw new Error('Could not delete this job. Please retry.');
      onDeleted(jobId);
    } catch {
      setError('Could not delete this job. Your download links are unchanged; please retry.');
    } finally {
      setPending(false);
    }
  }

  return <div className="grid gap-2 border-t border-border pt-3 text-xs text-text-secondary">
    {confirming ? <>
      <p>Remove access to this job and schedule its files for deletion? Download your fonts first. Files still used by another job are retained.</p>
      <div className="flex flex-wrap gap-2">
        <button type="button" className="secondary-button" disabled={pending} onClick={remove}>{pending ? 'Deleting…' : 'Confirm deletion'}</button>
        <button type="button" className="secondary-button" disabled={pending} onClick={() => setConfirming(false)}>Keep job</button>
      </div>
    </> : <button type="button" className="secondary-button" onClick={() => setConfirming(true)}>Delete this job and files</button>}
    {error && <p role="alert">{error}</p>}
  </div>;
}
