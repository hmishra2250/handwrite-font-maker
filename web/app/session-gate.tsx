'use client';

import { FormEvent, ReactNode, useEffect, useState } from 'react';
import type { RuntimeDeploymentMode } from '@/lib/server-auth';

type SessionState =
  | { status: 'loading' }
  | { status: 'authenticated'; email?: string | null; error?: string | null }
  | { status: 'anonymous'; error?: string | null };

export function SessionGate({ deploymentMode, children }: { deploymentMode: RuntimeDeploymentMode; children: ReactNode }) {
  const [session, setSession] = useState<SessionState>(deploymentMode === 'local' ? { status: 'authenticated' } : { status: 'loading' });
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    if (deploymentMode === 'local') return;
    let cancelled = false;
    fetch('/api/auth/session', { cache: 'no-store', credentials: 'same-origin' })
      .then((res) => res.json())
      .then((data: { authenticated?: boolean; user?: { email?: string | null } }) => {
        if (cancelled) return;
        setSession(data.authenticated ? { status: 'authenticated', email: data.user?.email } : { status: 'anonymous' });
      })
      .catch(() => {
        if (!cancelled) setSession({ status: 'anonymous', error: 'Could not check your beta session.' });
      });
    return () => { cancelled = true; };
  }, [deploymentMode]);

  async function login(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setSubmitting(true);
    setSession({ status: 'anonymous' });
    try {
      const res = await fetch('/api/auth/login', {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        credentials: 'same-origin',
        body: JSON.stringify({ email, password }),
      });
      const data = (await res.json()) as { authenticated?: boolean; user?: { email?: string | null }; error?: { message?: string } };
      if (!res.ok || !data.authenticated) throw new Error(data.error?.message ?? 'Sign in failed.');
      setPassword('');
      setSession({ status: 'authenticated', email: data.user?.email ?? email });
    } catch (err) {
      setSession({ status: 'anonymous', error: err instanceof Error ? err.message : 'Sign in failed.' });
    } finally {
      setSubmitting(false);
    }
  }

  async function logout() {
    setSubmitting(true);
    setSession((current) => current.status === 'authenticated' ? { ...current, error: null } : current);
    try {
      const res = await fetch('/api/auth/logout', { method: 'POST', credentials: 'same-origin' });
      if (!res.ok) throw new Error('Logout failed. Try again.');
      setPassword('');
      setSession({ status: 'anonymous' });
    } catch {
      setSession((current) => current.status === 'authenticated' ? { ...current, error: 'Logout failed. Try again.' } : current);
    } finally {
      setSubmitting(false);
    }
  }

  if (deploymentMode !== 'local' && session.status === 'loading') {
    return <div className="rounded-[22px] border border-border bg-surface p-7 text-sm text-text-secondary">Checking your invite beta session…</div>;
  }

  if (deploymentMode !== 'local' && session.status !== 'authenticated') {
    return (
      <section className="grid gap-4 rounded-[22px] border border-border bg-surface p-7" aria-labelledby="beta-login-title">
        <div>
          <span className="font-mono text-xs font-semibold uppercase tracking-[.08em] text-teal">Invite beta</span>
          <h2 id="beta-login-title" className="mt-2 text-2xl font-bold tracking-[-0.03em]">Sign in to capture your font</h2>
          <p className="mt-2 text-sm text-text-secondary">Use the email and password from your invite. Signups are closed for this private beta.</p>
        </div>
        <form className="grid gap-3" onSubmit={login}>
          <label className="grid gap-1.5 text-sm font-semibold text-text-primary">
            Email
            <input className="field" type="email" autoComplete="email" value={email} onChange={(event) => setEmail(event.target.value)} required />
          </label>
          <label className="grid gap-1.5 text-sm font-semibold text-text-primary">
            Password
            <input className="field" type="password" autoComplete="current-password" value={password} onChange={(event) => setPassword(event.target.value)} required />
          </label>
          {session.status === 'anonymous' && session.error && <p className="rounded-lg bg-red-muted px-3.5 py-2.5 text-[13px] text-red" role="alert">{session.error}</p>}
          <button type="submit" className="primary-button" disabled={submitting}>{submitting ? 'Signing in…' : 'Sign in'}</button>
        </form>
      </section>
    );
  }

  return (
    <div className="grid gap-4">
      {deploymentMode !== 'local' && (
        <div className="flex flex-wrap items-center justify-between gap-3 rounded-[18px] border border-border bg-surface px-4 py-3 text-sm text-text-secondary">
          <p>
            Signed in{session.status === 'authenticated' && session.email ? ` as ${session.email}` : ''}. Uploaded sources and generated files are retained temporarily for this beta; use Logout on shared devices.
          </p>
          <div className="grid gap-2 justify-items-start sm:justify-items-end">
            <button type="button" className="secondary-button" onClick={logout} disabled={submitting}>{submitting ? 'Logging out…' : 'Logout'}</button>
            {session.status === 'authenticated' && session.error && <p className="text-[13px] text-red" role="alert">{session.error}</p>}
          </div>
        </div>
      )}
      {children}
    </div>
  );
}
