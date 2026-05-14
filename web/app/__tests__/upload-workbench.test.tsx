import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { UploadWorkbench } from '../upload-workbench';

const validUploadResponse = {
  mode: 'demo' as const,
  uploadUrl: '/api/uploads/demo/jobs/job_test/input/original.jpg',
  method: 'PUT' as const,
  objectKey: 'jobs/job_test/input/original.jpg',
  bucket: 'test-bucket',
  expiresAt: new Date(Date.now() + 3600000).toISOString(),
  maxUploadBytes: 15 * 1024 * 1024,
};

const queuedJobResponse = {
  jobId: 'job_test',
  status: 'queued' as const,
  stage: 'queued' as const,
  progressLabel: 'Waiting for backend processing',
  warnings: [],
  artifacts: [],
  retentionExpiresAt: new Date(Date.now() + 86400000).toISOString(),
};

const succeededJobResponse = {
  ...queuedJobResponse,
  status: 'succeeded' as const,
  stage: 'complete' as const,
  progressLabel: 'Font build complete',
  artifacts: [
    { kind: 'otf', label: 'OpenType Font', objectKey: 'test.otf', url: '/test.otf', contentType: 'font/otf', sizeBytes: 1024 },
    { kind: 'ttf', label: 'TrueType Font', objectKey: 'test.ttf', url: '/test.ttf', contentType: 'font/ttf', sizeBytes: 1024 },
  ],
};

const failedJobResponse = {
  ...queuedJobResponse,
  status: 'failed' as const,
  stage: 'marker_detection' as const,
  error: {
    code: 'MARKER_NOT_FOUND' as const,
    message: 'Could not find all four page markers.',
    retryable: true,
  },
};

function createTestFile(name = 'template.jpg', type = 'image/jpeg', size = 1024) {
  return new File([new ArrayBuffer(size)], name, { type });
}

describe('UploadWorkbench', () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    URL.createObjectURL = vi.fn(() => 'blob:test-preview-url');
    URL.revokeObjectURL = vi.fn();
  });

  afterEach(() => {
    cleanup();
  });

  it('renders the upload form with capture zone', () => {
    render(<UploadWorkbench />);
    expect(screen.getByText('Take a photo or drag an image')).toBeInTheDocument();
    expect(screen.getByText('Build font')).toBeDisabled();
  });

  it('shows image preview after file selection', async () => {
    render(<UploadWorkbench />);
    const input = document.querySelector('input[type="file"]') as HTMLInputElement;
    const file = createTestFile();
    await userEvent.upload(input, file);
    expect(screen.getByAltText('Captured template preview')).toBeInTheDocument();
    expect(URL.createObjectURL).toHaveBeenCalledWith(file);
  });

  it('enables submit button when file is selected', async () => {
    render(<UploadWorkbench />);
    const input = document.querySelector('input[type="file"]') as HTMLInputElement;
    await userEvent.upload(input, createTestFile());
    expect(screen.getByText('Build font')).not.toBeDisabled();
  });

  it('removes file preview when remove button is clicked', async () => {
    render(<UploadWorkbench />);
    const input = document.querySelector('input[type="file"]') as HTMLInputElement;
    await userEvent.upload(input, createTestFile());
    expect(screen.getByAltText('Captured template preview')).toBeInTheDocument();
    const removeBtn = screen.getByLabelText('Remove photo');
    await userEvent.click(removeBtn);
    expect(screen.queryByAltText('Captured template preview')).not.toBeInTheDocument();
    expect(URL.revokeObjectURL).toHaveBeenCalled();
  });

  it('validates unsupported image types', async () => {
    render(<UploadWorkbench />);
    const input = document.querySelector('input[type="file"]') as HTMLInputElement;
    // Simulate setting an invalid file directly via fireEvent since userEvent.upload respects accept
    const pdfFile = createTestFile('doc.pdf', 'application/pdf');
    fireEvent.change(input, { target: { files: [pdfFile] } });
    await userEvent.click(screen.getByText('Build font'));
    expect(screen.getByRole('alert')).toHaveTextContent('JPEG, PNG, or WebP');
  });

  it('validates font name format', async () => {
    render(<UploadWorkbench />);
    const input = document.querySelector('input[type="file"]') as HTMLInputElement;
    await userEvent.upload(input, createTestFile());
    const fontInput = screen.getByDisplayValue('MyHandwrite-Regular');
    await userEvent.clear(fontInput);
    await userEvent.type(fontInput, 'bad font name');
    await userEvent.click(screen.getByText('Build font'));
    expect(screen.getByRole('alert')).toBeInTheDocument();
  });

  it('shows progress stages during polling', async () => {
    let pollCount = 0;
    vi.spyOn(globalThis, 'fetch').mockImplementation(async (url) => {
      const urlStr = typeof url === 'string' ? url : url.toString();
      if (urlStr.includes('/api/uploads')) {
        return Response.json(validUploadResponse);
      }
      if (urlStr.includes('/api/jobs/') && !urlStr.endsWith('/api/jobs')) {
        pollCount++;
        if (pollCount >= 2) return Response.json(succeededJobResponse);
        return Response.json({ ...queuedJobResponse, status: 'running', stage: 'font_generation' });
      }
      if (urlStr.endsWith('/api/jobs')) {
        return Response.json(queuedJobResponse, { status: 202 });
      }
      return Response.json({});
    });

    render(<UploadWorkbench />);
    const input = document.querySelector('input[type="file"]') as HTMLInputElement;
    await userEvent.upload(input, createTestFile());
    await userEvent.click(screen.getByText('Build font'));

    await waitFor(() => {
      expect(screen.getByText('Complete')).toBeInTheDocument();
    }, { timeout: 10000 });

    expect(screen.getByText('OpenType Font')).toBeInTheDocument();
    expect(screen.getByText('TrueType Font')).toBeInTheDocument();
  });

  it('shows error state on job failure', async () => {
    vi.spyOn(globalThis, 'fetch').mockImplementation(async (url) => {
      const urlStr = typeof url === 'string' ? url : url.toString();
      if (urlStr.includes('/api/uploads')) return Response.json(validUploadResponse);
      if (urlStr.includes('/api/jobs/') && !urlStr.endsWith('/api/jobs')) return Response.json(failedJobResponse);
      if (urlStr.endsWith('/api/jobs')) return Response.json(queuedJobResponse, { status: 202 });
      return Response.json({});
    });

    render(<UploadWorkbench />);
    const input = document.querySelector('input[type="file"]') as HTMLInputElement;
    await userEvent.upload(input, createTestFile());
    await userEvent.click(screen.getByText('Build font'));

    await waitFor(() => {
      expect(screen.getByText('Failed')).toBeInTheDocument();
    }, { timeout: 10000 });

    expect(screen.getByText('MARKER_NOT_FOUND')).toBeInTheDocument();
  });

  it('shows ready status when no job is active', () => {
    render(<UploadWorkbench />);
    expect(screen.getByText('Ready')).toBeInTheDocument();
    expect(screen.getByText('Upload a photographed template to start a font build.')).toBeInTheDocument();
  });
});
