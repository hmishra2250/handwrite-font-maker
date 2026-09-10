import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { CreateJobRequest } from '@/lib/contracts';
import { UploadWorkbench, normalizedPointInContainedImage } from '../upload-workbench';

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

function createTestFile(name = 'character.jpg', type = 'image/jpeg', size = 1024) {
  return new File([new ArrayBuffer(size)], name, { type });
}

function fileInputs() {
  return Array.from(document.querySelectorAll('input[type="file"]')) as HTMLInputElement[];
}

function uploadInput() {
  return fileInputs().find((input) => !input.hasAttribute('capture')) as HTMLInputElement;
}

function installImageAndCanvasMocks() {
  class MockImage {
    onload: (() => void) | null = null;
    onerror: (() => void) | null = null;
    naturalWidth = 2;
    naturalHeight = 2;
    width = 2;
    height = 2;
    decoding = 'async';
    set src(_value: string) {
      queueMicrotask(() => this.onload?.());
    }
  }
  vi.stubGlobal('Image', MockImage);
  vi.spyOn(HTMLCanvasElement.prototype, 'getContext').mockReturnValue({
    drawImage: vi.fn(),
    getImageData: vi.fn(() => ({ data: new Uint8ClampedArray([0, 0, 0, 255, 255, 255, 255, 255, 80, 80, 80, 255, 240, 240, 240, 255]) })),
    putImageData: vi.fn(),
  } as unknown as CanvasRenderingContext2D);
  vi.spyOn(HTMLCanvasElement.prototype, 'toBlob').mockImplementation(function toBlob(callback: BlobCallback) {
    callback(new Blob(['mask-png'], { type: 'image/png' }));
  });
}

describe('UploadWorkbench', () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    URL.createObjectURL = vi.fn(() => 'blob:test-preview-url');
    URL.revokeObjectURL = vi.fn();
    installImageAndCanvasMocks();
  });

  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
  });

  it('renders capture modes with guided mode active by default', () => {
    render(<UploadWorkbench />);
    expect(screen.getByRole('tab', { name: /Guided characters/i })).toHaveAttribute('aria-selected', 'true');
    expect(screen.getByText('Current character')).toBeInTheDocument();
    expect(screen.getByText('Build guided font (0 accepted)')).toBeDisabled();
  });

  it('has camera input with capture attribute for mobile', () => {
    render(<UploadWorkbench />);
    const cameraInput = fileInputs().find((input) => input.hasAttribute('capture'));
    expect(cameraInput).toBeTruthy();
    expect(cameraInput?.getAttribute('capture')).toBe('environment');
    expect(cameraInput?.getAttribute('accept')).toContain('image/jpeg');
  });

  it('has a file input without capture for desktop uploads', () => {
    render(<UploadWorkbench />);
    const fileInput = uploadInput();
    expect(fileInput).toBeTruthy();
    expect(fileInput.getAttribute('accept')).toContain('image/jpeg');
  });

  it('normalizes page-corner clicks against the rendered image content, not letterbox padding', () => {
    const point = normalizedPointInContainedImage(200, 150, { left: 100, top: 100, width: 200, height: 200 }, 200, 100);
    expect(point[0]).toBeCloseTo(0.5);
    expect(point[1]).toBeCloseTo(0);

    const lowerPoint = normalizedPointInContainedImage(200, 250, { left: 100, top: 100, width: 200, height: 200 }, 200, 100);
    expect(lowerPoint[0]).toBeCloseTo(0.5);
    expect(lowerPoint[1]).toBeCloseTo(1);
  });

  it('shows guided source and mask preview after file selection', async () => {
    render(<UploadWorkbench />);
    const file = createTestFile();
    await userEvent.upload(uploadInput(), file);
    expect(screen.getByAltText('Source photo for A')).toBeInTheDocument();
    await waitFor(() => expect(screen.getByAltText('Black-on-white mask for A')).toBeInTheDocument());
    expect(URL.createObjectURL).toHaveBeenCalledWith(file);
  });

  it('accepts a guided glyph, advances, and retains it in the grid', async () => {
    render(<UploadWorkbench />);
    await userEvent.upload(uploadInput(), createTestFile());
    await waitFor(() => expect(screen.getByAltText('Black-on-white mask for A')).toBeInTheDocument());
    await userEvent.click(screen.getByText('Accept A'));
    expect(screen.getByLabelText('B missing')).toBeInTheDocument();
    expect(screen.getByText('1 accepted · 93 missing')).toBeInTheDocument();
    expect(screen.getByLabelText('A accepted')).toBeInTheDocument();
  });

  it('previous next and redo only affect the selected guided glyph', async () => {
    render(<UploadWorkbench />);
    await userEvent.upload(uploadInput(), createTestFile());
    await waitFor(() => expect(screen.getByAltText('Black-on-white mask for A')).toBeInTheDocument());
    await userEvent.click(screen.getByText('Accept A'));
    await userEvent.click(screen.getByText('Previous'));
    expect(screen.getByText('Redo A')).not.toBeDisabled();
    await userEvent.click(screen.getByText('Redo A'));
    expect(screen.getByLabelText('A missing')).toBeInTheDocument();
    expect(screen.getByText('0 accepted · 94 missing')).toBeInTheDocument();
  });

  it('extracts experimental object cutout from the original guided source and accepts that mask', async () => {
    const maskDataUrl = `data:image/png;base64,${btoa('mask-png')}`;
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockImplementation(async (url) => {
      const urlStr = typeof url === 'string' ? url : url.toString();
      if (urlStr.includes('/api/uploads')) return Response.json(validUploadResponse);
      if (urlStr.includes('/api/capture/foreground')) return Response.json({ maskDataUrl, width: 2, height: 2, method: 'grabcut' });
      if (urlStr.endsWith('/api/jobs')) return Response.json(queuedJobResponse, { status: 202 });
      return Response.json({});
    });

    render(<UploadWorkbench />);
    await userEvent.upload(uploadInput(), createTestFile('leaf.jpg'));
    await waitFor(() => expect(screen.getByAltText('Black-on-white mask for A')).toBeInTheDocument());
    await userEvent.click(screen.getByLabelText(/Experimental object cutout/i));
    expect(screen.getAllByText(/solid monochrome silhouette/i).length).toBeGreaterThan(0);
    await userEvent.click(screen.getByText('Extract object'));
    await waitFor(() => expect(screen.getByText(/Object cutout ready/)).toBeInTheDocument());
    await userEvent.click(screen.getByText('Accept A'));
    await userEvent.click(screen.getByText('Build guided font (1 accepted)'));

    await waitFor(() => expect(fetchMock).toHaveBeenCalledWith('/api/jobs', expect.anything()));
    const foregroundCall = fetchMock.mock.calls.find(([url]) => String(url).includes('/api/capture/foreground'));
    const foregroundBody = JSON.parse(String((foregroundCall?.[1] as RequestInit).body));
    expect(foregroundBody).toMatchObject({ inputPhoto: expect.objectContaining({ objectKey: validUploadResponse.objectKey }), rectangle: [0.12, 0.12, 0.88, 0.88] });
    const jobsCall = fetchMock.mock.calls.find(([url]) => String(url).endsWith('/api/jobs'));
    const body = JSON.parse(String((jobsCall?.[1] as RequestInit).body)) as CreateJobRequest;
    expect(body.capture?.mode).toBe('guided');
    if (body.capture?.mode !== 'guided') throw new Error('Expected guided capture');
    expect(body.capture.glyphs[0]).toMatchObject({ char: 'A', baseline: 0.8 });
  });

  it('submits guided capture with the accepted mask as both outer and glyph inputPhoto', async () => {
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockImplementation(async (url) => {
      const urlStr = typeof url === 'string' ? url : url.toString();
      if (urlStr.includes('/api/uploads')) return Response.json(validUploadResponse);
      if (urlStr.endsWith('/api/jobs')) return Response.json(queuedJobResponse, { status: 202 });
      return Response.json({});
    });

    render(<UploadWorkbench />);
    await userEvent.upload(uploadInput(), createTestFile());
    await waitFor(() => expect(screen.getByAltText('Black-on-white mask for A')).toBeInTheDocument());
    await userEvent.click(screen.getByText('Accept A'));
    await userEvent.click(screen.getByText('Build guided font (1 accepted)'));

    await waitFor(() => expect(fetchMock).toHaveBeenCalledWith('/api/jobs', expect.anything()));
    const jobsCall = fetchMock.mock.calls.find(([url]) => String(url).endsWith('/api/jobs'));
    const body = JSON.parse(String((jobsCall?.[1] as RequestInit).body)) as CreateJobRequest;
    expect(body.capture?.mode).toBe('guided');
    if (body.capture?.mode !== 'guided') throw new Error('Expected guided capture');
    expect(body.inputPhoto).toEqual(body.capture.glyphs[0].inputPhoto);
    expect(body.capture).toMatchObject({ mode: 'guided', format: 'mask-v1' });
    expect(body.capture.glyphs[0]).toMatchObject({ char: 'A', baseline: 0.8 });
  });

  it('switches to markerless sheet mode and requires confirmed corners', async () => {
    render(<UploadWorkbench />);
    await userEvent.click(screen.getByRole('tab', { name: /Markerless A4 sheet/i }));
    await userEvent.upload(uploadInput(), createTestFile('sheet.jpg'));
    expect(screen.getByText('Build markerless sheet font')).toBeDisabled();
    await userEvent.click(screen.getByText('Confirm page corners'));
    expect(screen.getByText('Confirmed for job submission.')).toBeInTheDocument();
  });

  it('submits markerless page capture with default-v1 A4 confirmed corners', async () => {
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockImplementation(async (url) => {
      const urlStr = typeof url === 'string' ? url : url.toString();
      if (urlStr.includes('/api/uploads')) return Response.json(validUploadResponse);
      if (urlStr.endsWith('/api/jobs')) return Response.json(queuedJobResponse, { status: 202 });
      return Response.json({});
    });
    render(<UploadWorkbench />);
    await userEvent.click(screen.getByRole('tab', { name: /Markerless A4 sheet/i }));
    await userEvent.upload(uploadInput(), createTestFile('sheet.jpg'));
    await userEvent.click(screen.getByText('Confirm page corners'));
    await userEvent.click(screen.getByText('Build markerless sheet font'));
    await waitFor(() => expect(fetchMock).toHaveBeenCalledWith('/api/jobs', expect.anything()));
    const jobsCall = fetchMock.mock.calls.find(([url]) => String(url).endsWith('/api/jobs'));
    const body = JSON.parse(String((jobsCall?.[1] as RequestInit).body)) as CreateJobRequest;
    expect(body.capture?.mode).toBe('template');
    if (body.capture?.mode !== 'template') throw new Error('Expected template capture');
    expect(body.capture).toMatchObject({ mode: 'template', templateId: 'default-v1', paperSize: 'A4', alignment: 'page' });
    expect(body.capture.corners).toHaveLength(4);
  });

  it('legacy mode keeps the old no-capture job shape', async () => {
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockImplementation(async (url) => {
      const urlStr = typeof url === 'string' ? url : url.toString();
      if (urlStr.includes('/api/uploads')) return Response.json(validUploadResponse);
      if (urlStr.endsWith('/api/jobs')) return Response.json(queuedJobResponse, { status: 202 });
      return Response.json({});
    });
    render(<UploadWorkbench />);
    await userEvent.click(screen.getByRole('tab', { name: /Legacy marker sheet/i }));
    await userEvent.upload(uploadInput(), createTestFile('template.jpg'));
    await userEvent.click(screen.getByText('Build legacy marker font'));
    await waitFor(() => expect(fetchMock).toHaveBeenCalledWith('/api/jobs', expect.anything()));
    const jobsCall = fetchMock.mock.calls.find(([url]) => String(url).endsWith('/api/jobs'));
    const body = JSON.parse(String((jobsCall?.[1] as RequestInit).body)) as CreateJobRequest;
    expect(body.capture).toBeUndefined();
  });

  it('validates unsupported image types', async () => {
    render(<UploadWorkbench />);
    fireEvent.change(uploadInput(), { target: { files: [createTestFile('doc.pdf', 'application/pdf')] } });
    await userEvent.click(screen.getByText('Accept A'));
    await userEvent.click(screen.getByText('Build guided font (0 accepted)'));
    expect(screen.getByRole('alert')).toHaveTextContent('JPEG, PNG, or WebP');
  });

  it('validates font name format', async () => {
    render(<UploadWorkbench />);
    await userEvent.upload(uploadInput(), createTestFile());
    await waitFor(() => expect(screen.getByAltText('Black-on-white mask for A')).toBeInTheDocument());
    await userEvent.click(screen.getByText('Accept A'));
    const fontInput = screen.getByDisplayValue('MyHandwrite-Regular');
    await userEvent.clear(fontInput);
    await userEvent.type(fontInput, 'bad font name');
    await userEvent.click(screen.getByText('Build guided font (1 accepted)'));
    expect(screen.getByRole('alert')).toBeInTheDocument();
  });

  it('shows progress stages during polling and completes with downloads and typed proof', async () => {
    let pollCount = 0;
    vi.spyOn(globalThis, 'fetch').mockImplementation(async (url) => {
      const urlStr = typeof url === 'string' ? url : url.toString();
      if (urlStr.includes('/api/uploads')) return Response.json(validUploadResponse);
      if (urlStr.includes('/api/jobs/') && !urlStr.endsWith('/api/jobs')) {
        pollCount++;
        if (pollCount >= 2) return Response.json(succeededJobResponse);
        return Response.json({ ...queuedJobResponse, status: 'running', stage: 'font_generation' });
      }
      if (urlStr.endsWith('/api/jobs')) return Response.json(queuedJobResponse, { status: 202 });
      return Response.json({});
    });
    vi.stubGlobal('FontFace', class { constructor(public family: string) {} async load() { return this; } });
    Object.defineProperty(document, 'fonts', { value: { add: vi.fn() }, configurable: true });

    render(<UploadWorkbench />);
    await userEvent.upload(uploadInput(), createTestFile());
    await waitFor(() => expect(screen.getByAltText('Black-on-white mask for A')).toBeInTheDocument());
    await userEvent.click(screen.getByText('Accept A'));
    await userEvent.click(screen.getByText('Build guided font (1 accepted)'));

    await waitFor(() => expect(screen.getByText('Complete')).toBeInTheDocument(), { timeout: 10000 });
    expect(screen.getByText('OpenType Font')).toBeInTheDocument();
    expect(screen.getByText('TrueType Font')).toBeInTheDocument();
    expect(screen.getByText('Typed proof from generated TTF')).toBeInTheDocument();
    expect(screen.getByDisplayValue('A')).toBeInTheDocument();
    expect(screen.getByText(/How to install/)).toBeInTheDocument();
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
    await userEvent.upload(uploadInput(), createTestFile());
    await waitFor(() => expect(screen.getByAltText('Black-on-white mask for A')).toBeInTheDocument());
    await userEvent.click(screen.getByText('Accept A'));
    await userEvent.click(screen.getByText('Build guided font (1 accepted)'));

    await waitFor(() => expect(screen.getByText('Failed')).toBeInTheDocument(), { timeout: 10000 });
    expect(screen.getByText('MARKER_NOT_FOUND')).toBeInTheDocument();
  });

  it('shows ready status when no job is active', () => {
    render(<UploadWorkbench />);
    expect(screen.getByText('Ready')).toBeInTheDocument();
    expect(screen.getByText('Choose a capture mode, then build with a configured Python worker.')).toBeInTheDocument();
  });
});
