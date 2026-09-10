export const USAGE_CONSENT_KEY = 'hfm-share-usage-v1';
export type FunnelEvent = 'upload_complete' | 'glyph_accepted' | 'build_succeeded' | 'font_download_requested' | 'font_used';

export function recordFunnelEvent(event: FunnelEvent): void {
  try {
    if (typeof window === 'undefined' || localStorage.getItem(USAGE_CONSENT_KEY) !== 'true') return;
    // No project IDs, filenames, images, font/proof text, or third-party calls.
    void fetch('/api/events', {
      method: 'POST', credentials: 'same-origin', headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ event, consent: true }),
    }).catch(() => undefined);
  } catch { /* Telemetry must never interrupt capture or claim to have succeeded. */ }
}
