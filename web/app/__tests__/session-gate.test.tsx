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
    await userEvent.click(screen.getByLabelText('Account and settings'));
    await userEvent.click(screen.getByRole('button', { name: /^Logout$/ }));

    expect(await screen.findByRole('alert')).toHaveTextContent('Logout failed. Try again.');
    expect(screen.getByText(/Signed in as invitee@example.com/)).toBeInTheDocument();
    expect(screen.queryByRole('heading', { name: /Sign in to capture your font/i })).not.toBeInTheDocument();
    await waitFor(() => expect(screen.getByRole('button', { name: /^Logout$/ })).toBeEnabled());
  });
  it('keeps the workspace mounted when opening and closing account settings', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(Response.json({ authenticated: true, user: { email: 'maker@example.test' } })));
    render(<SessionGate deploymentMode="invite_beta"><input aria-label="Draft font name" defaultValue="" /></SessionGate>);
    const draft = await screen.findByLabelText('Draft font name');
    await userEvent.type(draft, 'My first font');
    const account = screen.getByLabelText('Account and settings');
    expect(account.closest('details')).not.toHaveAttribute('open');
    await userEvent.click(account);
    expect(account.closest('details')).toHaveAttribute('open');
    await userEvent.click(account);
    expect(draft).toHaveValue('My first font');
  });

  it('shows a focused sign-in instead of the capture tools before authentication', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(Response.json({ authenticated: false })));
    render(<SessionGate deploymentMode="private_alpha"><div>Protected capture tools</div></SessionGate>);
    expect(await screen.findByRole('button', { name: 'Sign in' })).toBeInTheDocument();
    expect(screen.getByRole('heading', { level: 1 })).toHaveTextContent('A little more');
    expect(screen.queryByText('Protected capture tools')).not.toBeInTheDocument();
    expect(screen.getByLabelText('Email')).toHaveAttribute('autocomplete', 'email');
    expect(screen.getByLabelText('Password')).toHaveAttribute('autocomplete', 'current-password');
  });

  it('protects the mobile capture surface with a focused phone login', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(Response.json({ authenticated: false })));
    render(<SessionGate deploymentMode="private_alpha" surface="mobile"><div>Protected phone capture</div></SessionGate>);

    expect(await screen.findByRole('button', { name: 'Sign in' })).toBeInTheDocument();
    expect(screen.getByRole('heading', { level: 1 })).toHaveTextContent('Capture your fontfrom your phone.');
    expect(screen.queryByText('Protected phone capture')).not.toBeInTheDocument();
    expect(document.querySelector('.studio-specimen')).not.toBeInTheDocument();
    expect(document.querySelector('.studio-sidebar')).not.toBeInTheDocument();
  });

  it('renders authenticated mobile capture without the resource sidebar while retaining account logout', async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url === '/api/auth/session') {
        return Response.json({ authenticated: true, user: { email: 'phone@example.test' } });
      }
      if (url === '/api/auth/logout') {
        return Response.json({ authenticated: false });
      }
      throw new Error(`unexpected fetch ${url}`);
    });
    vi.stubGlobal('fetch', fetchMock);

    render(<SessionGate deploymentMode="private_alpha" surface="mobile"><div>Phone workbench</div></SessionGate>);

    expect(await screen.findByText('Phone workbench')).toBeInTheDocument();
    expect(document.querySelector('.mobile-capture-layout')).toBeInTheDocument();
    expect(document.querySelector('.studio-sidebar')).not.toBeInTheDocument();
    expect(screen.queryByText('RESOURCES')).not.toBeInTheDocument();
    await userEvent.click(screen.getByLabelText('Account and settings'));
    expect(screen.getByText(/Signed in as phone@example.test/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: /^Logout$/ }));
    expect(await screen.findByRole('button', { name: 'Sign in' })).toBeInTheDocument();
  });

});
