import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, expect, it, vi } from 'vitest';
import { FeedbackPanel } from '../feedback-panel';
import { recordFunnelEvent, USAGE_CONSENT_KEY } from '@/lib/feedback-client';
let preferences: Map<string, string>;
beforeEach(() => {
  vi.restoreAllMocks(); preferences = new Map();
  vi.stubGlobal('localStorage', { getItem: (key: string) => preferences.get(key) ?? null, setItem: (key: string, value: string) => preferences.set(key, value) });
});
it('usage is off by default and sends only the allowlisted count after opting in', () => {
  const fetcher = vi.spyOn(globalThis, 'fetch').mockResolvedValue(Response.json({ ok: true }));
  recordFunnelEvent('glyph_accepted'); expect(fetcher).not.toHaveBeenCalled();
  preferences.set(USAGE_CONSENT_KEY, 'true'); recordFunnelEvent('glyph_accepted');
  expect(fetcher).toHaveBeenCalledWith('/api/events', expect.objectContaining({ body: '{"event":"glyph_accepted","consent":true}' }));
});
it('requires feedback consent and preserves text after failure', async () => {
  vi.spyOn(globalThis, 'fetch').mockResolvedValue(Response.json({}, { status: 503 }));
  render(<FeedbackPanel />);
  fireEvent.click(screen.getByText('Report a bad extraction or installation problem'));
  fireEvent.change(screen.getByLabelText('What went wrong?'), { target: { value: 'The leaf edge disappeared.' } });
  expect(screen.getByRole('button', { name: 'Send feedback' })).toBeDisabled();
  fireEvent.click(screen.getByLabelText('Send this text to the beta team for review'));
  fireEvent.click(screen.getByRole('button', { name: 'Send feedback' }));
  await waitFor(() => expect(screen.getByRole('status')).toHaveTextContent('Feedback was not saved'));
  expect(screen.getByLabelText('What went wrong?')).toHaveValue('The leaf edge disappeared.');
});
