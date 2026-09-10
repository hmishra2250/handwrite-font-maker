'use client';

import { FormEvent, useEffect, useState } from 'react';

type AccountPayload = {
  user: { id: string; email: string | null };
  plan: { id: string; name: string; billingEnabled: boolean };
  limits: { dailyUploads: number; dailyUploadBytes: number; dailyPreviews: number; dailyBuilds: number; activeJobs: number };
  retention: { projectDays: number; downloadHours: number };
};

type AccountState =
  | { status: 'loading' }
  | { status: 'ready'; account: AccountPayload }
  | { status: 'error'; message: string };

function megabytes(bytes: number) {
  return `${Math.round(bytes / 1024 / 1024)} MB`;
}

export function AccountPanel({ onSignedOut }: { onSignedOut: (message?: string) => void }) {
  const [account, setAccount] = useState<AccountState>({ status: 'loading' });
  const [currentPassword, setCurrentPassword] = useState('');
  const [newPassword, setNewPassword] = useState('');
  const [changing, setChanging] = useState(false);
  const [passwordMessage, setPasswordMessage] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    fetch('/api/account', { cache: 'no-store', credentials: 'same-origin' })
      .then(async (res) => {
        const data = await res.json();
        if (!res.ok) throw new Error(data?.error?.message ?? 'Could not load account.');
        return data as AccountPayload;
      })
      .then((data) => {
        if (!cancelled) setAccount({ status: 'ready', account: data });
      })
      .catch((err) => {
        if (!cancelled) setAccount({ status: 'error', message: err instanceof Error ? err.message : 'Could not load account.' });
      });
    return () => { cancelled = true; };
  }, []);

  async function changePassword(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setChanging(true);
    setPasswordMessage(null);
    try {
      const res = await fetch('/api/auth/password', {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        credentials: 'same-origin',
        body: JSON.stringify({ currentPassword, newPassword }),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(data?.error?.message ?? 'Password change failed.');
      setCurrentPassword('');
      setNewPassword('');
      onSignedOut('Password changed. Sign in again with the new password.');
    } catch (err) {
      setPasswordMessage(err instanceof Error ? err.message : 'Password change failed.');
    } finally {
      setChanging(false);
    }
  }

  return (
    <section className="grid gap-4 rounded-[18px] border border-border bg-surface px-4 py-4 text-sm" aria-labelledby="account-panel-title">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <span className="font-mono text-[11px] font-semibold uppercase tracking-[.08em] text-teal">Account</span>
          <h2 id="account-panel-title" className="mt-1 text-lg font-bold tracking-[-0.02em] text-text-primary">Your account</h2>
        </div>
        {account.status === 'ready' && (
          <span className="rounded-full bg-teal-muted px-3 py-1 text-xs font-semibold text-teal">{account.account.plan.name}</span>
        )}
      </div>

      {account.status === 'loading' && <p className="text-text-secondary">Loading account limits…</p>}
      {account.status === 'error' && <p className="text-red" role="alert">{account.message}</p>}
      {account.status === 'ready' && (
        <div className="grid gap-3 text-text-secondary">
          <p>
            Your invitation includes free alpha access within the limits below. Payments are not available yet.
          </p>
          <dl className="grid grid-cols-2 gap-2 md:grid-cols-5">
            {[
              ['Uploads/day', account.account.limits.dailyUploads],
              ['Upload bytes/day', megabytes(account.account.limits.dailyUploadBytes)],
              ['Previews/day', account.account.limits.dailyPreviews],
              ['Builds/day', account.account.limits.dailyBuilds],
              ['Active jobs', account.account.limits.activeJobs],
            ].map(([label, value]) => (
              <div key={label} className="rounded-xl border border-border bg-bg-subtle px-3 py-2">
                <dt className="text-[10px] uppercase tracking-[.06em] text-text-tertiary">{label}</dt>
                <dd className="mt-0.5 font-bold text-text-primary">{value}</dd>
              </div>
            ))}
          </dl>
          <p className="text-xs text-text-tertiary">Projects are retained for {account.account.retention.projectDays} days; downloads are retained for {account.account.retention.downloadHours} hours.</p>
        </div>
      )}

      <details className="rounded-xl border border-border bg-bg-subtle p-3">
        <summary className="cursor-pointer text-sm font-semibold text-text-primary">Change password</summary>
        <form className="mt-3 grid gap-3" onSubmit={changePassword}>
          <label className="grid gap-1.5 text-sm font-semibold text-text-primary">
            Current password
            <input className="field bg-surface" type="password" autoComplete="current-password" value={currentPassword} onChange={(event) => setCurrentPassword(event.target.value)} minLength={12} maxLength={256} required />
          </label>
          <label className="grid gap-1.5 text-sm font-semibold text-text-primary">
            New password
            <input className="field bg-surface" type="password" autoComplete="new-password" value={newPassword} onChange={(event) => setNewPassword(event.target.value)} minLength={12} maxLength={256} required />
          </label>
          {passwordMessage && <p className="text-[13px] text-red" role="alert">{passwordMessage}</p>}
          <button type="submit" className="secondary-button justify-center" disabled={changing}>{changing ? 'Changing…' : 'Change password'}</button>
          <p className="text-xs text-text-tertiary">Changing your password signs out every active alpha session.</p>
        </form>
      </details>
    </section>
  );
}
