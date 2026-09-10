import { cleanup, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { SessionGate } from '../session-gate';

describe('SessionGate', () => {
  afterEach(() => {
    cleanup();
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
  });

  it('keeps the signed-in gate visible and shows retry copy when logout fails', async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url === '/api/auth/session') {
        return Response.json({ authenticated: true, user: { email: 'invitee@example.com' } });
      }
      if (url === '/api/auth/logout') {
        return Response.json({ error: { code: 'INTERNAL_ERROR', message: 'temporary failure' } }, { status: 503 });
      }
      throw new Error(`unexpected fetch ${url}`);
    });
    vi.stubGlobal('fetch', fetchMock);

    render(<SessionGate deploymentMode="invite_beta"><div>Workbench</div></SessionGate>);

    expect(await screen.findByText('Workbench')).toBeInTheDocument();
    expect(screen.getByText(/Signed in as invitee@example.com/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: /^Logout$/ }));

    expect(await screen.findByRole('alert')).toHaveTextContent('Logout failed. Try again.');
    expect(screen.getByText(/Signed in as invitee@example.com/)).toBeInTheDocument();
    expect(screen.queryByRole('heading', { name: /Sign in to capture your font/i })).not.toBeInTheDocument();
    await waitFor(() => expect(screen.getByRole('button', { name: /^Logout$/ })).toBeEnabled());
  });
});
