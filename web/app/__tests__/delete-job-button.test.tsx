import { cleanup, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, expect, it, vi } from 'vitest';
import { DeleteJobButton } from '../delete-job-button';

afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

it('requires explicit confirmation and reports only successful deletion', async () => {
  const user = userEvent.setup();
  const fetcher = vi.fn().mockResolvedValue(new Response('{}', { status: 200 }));
  vi.stubGlobal('fetch', fetcher);
  const deleted = vi.fn();
  render(<DeleteJobButton jobId="job_one" onDeleted={deleted} />);
  await user.click(screen.getByRole('button', { name: 'Delete this job and files' }));
  expect(fetcher).not.toHaveBeenCalled();
  await user.click(screen.getByRole('button', { name: 'Keep job' }));
  expect(fetcher).not.toHaveBeenCalled();
  await user.click(screen.getByRole('button', { name: 'Delete this job and files' }));
  await user.click(screen.getByRole('button', { name: 'Confirm deletion' }));
  expect(fetcher).toHaveBeenCalledWith('/api/jobs/job_one', { method: 'DELETE', credentials: 'same-origin' });
  expect(deleted).toHaveBeenCalledWith('job_one');
});

it('keeps the job visible and allows retry after a server failure', async () => {
  const user = userEvent.setup();
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response('{}', { status: 503 })));
  const deleted = vi.fn();
  render(<DeleteJobButton jobId="job_one" onDeleted={deleted} />);
  await user.click(screen.getByRole('button', { name: 'Delete this job and files' }));
  await user.click(screen.getByRole('button', { name: 'Confirm deletion' }));
  expect(await screen.findByRole('alert')).toHaveTextContent('please retry');
  expect(deleted).not.toHaveBeenCalled();
  expect(screen.getByRole('button', { name: 'Confirm deletion' })).toBeEnabled();
});
