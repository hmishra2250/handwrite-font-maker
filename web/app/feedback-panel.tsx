'use client';
import { useState, useSyncExternalStore, type FormEvent } from 'react';
import { recordFunnelEvent, USAGE_CONSENT_KEY } from '@/lib/feedback-client';

function readUsageConsent() {
  try { return localStorage.getItem(USAGE_CONSENT_KEY) === 'true'; } catch { return false; }
}
function subscribeUsageConsent(listener: () => void) {
  window.addEventListener('storage', listener);
  window.addEventListener('hfm-usage-consent', listener);
  return () => { window.removeEventListener('storage', listener); window.removeEventListener('hfm-usage-consent', listener); };
}

export function FeedbackPanel() {
  const shareUsage = useSyncExternalStore(subscribeUsageConsent, readUsageConsent, () => false);
  const [topic, setTopic] = useState('extraction');
  const [message, setMessage] = useState('');
  const [consent, setConsent] = useState(false);
  const [pending, setPending] = useState(false);
  const [status, setStatus] = useState<string | null>(null);
  function toggleUsage(enabled: boolean) {
    try {
      localStorage.setItem(USAGE_CONSENT_KEY, String(enabled));
      window.dispatchEvent(new Event('hfm-usage-consent'));
      setStatus(null);
    } catch { setStatus('This browser cannot save the preference; usage sharing remains off.'); }
  }
  async function submit(event: FormEvent) {
    event.preventDefault();
    if (!consent || message.trim().length < 10 || pending) return;
    setPending(true);
    setStatus(null);
    try {
      const response = await fetch('/api/feedback', {
        method: 'POST', credentials: 'same-origin', headers: { 'content-type': 'application/json' },
        body: JSON.stringify({ topic, message: message.trim(), consent: true }),
      });
      if (!response.ok) throw new Error('failed');
      setMessage(''); setConsent(false);
      setStatus('Feedback saved for beta review. Thank you.');
    } catch { setStatus('Feedback was not saved. Your text is still here; please retry.'); }
    finally { setPending(false); }
  }
  return <section className="mt-8 rounded-[22px] border border-border bg-surface p-6 text-sm" aria-labelledby="feedback-heading">
    <h2 id="feedback-heading" className="text-lg font-semibold">Help improve the beta</h2>
    <p className="mt-2 text-text-secondary">Optional usage counts help us find where capture gets stuck. Counts are linked to your account, retained for 30 days, and never contain images, filenames, or font text. No third-party analytics.</p>
    <label className="mt-3 flex items-start gap-2"><input type="checkbox" checked={shareUsage} onChange={e => toggleUsage(e.target.checked)} />Share basic usage counts</label>
    {shareUsage && <button type="button" className="secondary-button mt-3" onClick={() => { recordFunnelEvent('font_used'); setStatus('Usage confirmation requested. This does not validate Office compatibility.'); }}>I used my font in another app</button>}
    <details className="mt-5">
      <summary className="cursor-pointer font-semibold">Report a bad extraction or installation problem</summary>
      <form onSubmit={submit} className="mt-4 grid max-w-xl gap-3">
        <label>Feedback topic<select className="form-input mt-1 w-full" value={topic} onChange={e => setTopic(e.target.value)} disabled={pending}><option value="extraction">Extraction</option><option value="installation">Installation</option><option value="other">Other</option></select></label>
        <label>What went wrong?<textarea className="form-input mt-1 min-h-24 w-full" minLength={10} maxLength={1000} value={message} onChange={e => setMessage(e.target.value)} required disabled={pending} /></label>
        <p className="text-xs text-text-secondary">Text only. Do not include passwords, personal details, or private font content. Images are not attached. Feedback is linked to your account and retained for 30 days.</p>
        <label className="flex items-start gap-2"><input type="checkbox" checked={consent} onChange={e => setConsent(e.target.checked)} disabled={pending} />Send this text to the beta team for review</label>
        <button className="secondary-button" disabled={pending || !consent || message.trim().length < 10}>{pending ? 'Sending…' : 'Send feedback'}</button>
      </form>
    </details>
    {status && <p className="mt-3 text-text-secondary" role="status">{status}</p>}
  </section>;
}
