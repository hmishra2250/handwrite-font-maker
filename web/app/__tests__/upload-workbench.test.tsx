import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { CreateJobRequest } from '@/lib/contracts';
import type { FontProject, ProjectPayload } from '@/lib/projects';
import { UploadWorkbench, maskCanvasPointFromClient, normalizedPointInContainedImage } from '../upload-workbench';

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

function createProjectFixture(overrides: Partial<FontProject> = {}): FontProject {
  return {
    id: 'project_1',
    revision: 1,
    name: 'Queued Project',
    font: { fontName: 'MyHandwrite-Regular', familyName: 'My Handwrite', styleName: 'Regular' },
    mode: 'guided',
    targetCharacters: 'ABCDE',
    glyphs: [],
    sheet: null,
    lastJobId: null,
    createdAt: new Date(Date.now() - 1000).toISOString(),
    updatedAt: new Date(Date.now() - 1000).toISOString(),
    retentionExpiresAt: new Date(Date.now() + 86400000).toISOString(),
    ...overrides,
  };
}

function createTestFile(name = 'character.jpg', type = 'image/jpeg', size = 1024) {
  return new File([new ArrayBuffer(size)], name, { type });
}

function fileInputs() {
  return Array.from(document.querySelectorAll('input[type="file"]')) as HTMLInputElement[];
}

function uploadInput() {
  return fileInputs().find((input) => !input.hasAttribute('capture')) as HTMLInputElement;
}

function expandProjectControls() {
  const summary = screen.getByText('Project').closest('summary');
  if (!summary) throw new Error('Project summary not found.');
  if (!summary.closest('details')?.hasAttribute('open')) fireEvent.click(summary);
}

function expandRefinementTools() {
  const summary = screen.getByText('Refinement tools').closest('summary');
  if (!summary) throw new Error('Refinement summary not found.');
  if (!summary.closest('details')?.hasAttribute('open')) fireEvent.click(summary);
}

function expandFontSettings() {
  const summary = screen.getByText('Font settings').closest('summary');
  if (!summary) throw new Error('Font settings summary not found.');
  if (!summary.closest('details')?.hasAttribute('open')) fireEvent.click(summary);
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
  let currentData = new Uint8ClampedArray([0, 0, 0, 255, 255, 255, 255, 255, 80, 80, 80, 255, 240, 240, 240, 255]);
  vi.spyOn(HTMLCanvasElement.prototype, 'getContext').mockReturnValue({
    drawImage: vi.fn(),
    fillRect: vi.fn(),
    fillText: vi.fn(),
    fillStyle: '',
    font: '',
    textAlign: 'center',
    textBaseline: 'middle',
    getImageData: vi.fn(() => ({ data: new Uint8ClampedArray(currentData), width: 2, height: 2 })),
    putImageData: vi.fn((imageData: ImageData) => {
      currentData = new Uint8ClampedArray(imageData.data);
    }),
  } as unknown as CanvasRenderingContext2D);
  vi.spyOn(HTMLCanvasElement.prototype, 'toBlob').mockImplementation(function toBlob(callback: BlobCallback) {
    callback(new Blob([Array.from(currentData).join(',')], { type: 'image/png' }));
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
    expect(screen.getByText('Capture A')).toBeInTheDocument();
    expect(screen.getByText('Build guided font (0 accepted)')).toBeDisabled();
  });

  it('can render as a constrained mobile phone-capture workbench without the marketing subtitle', () => {
    render(<UploadWorkbench presentation="mobile" />);
    expect(screen.getByRole('heading', { name: 'Capture your font' })).toBeInTheDocument();
    expect(screen.getByText('Phone capture alpha')).toBeInTheDocument();
    expect(screen.queryByText('Your handwriting. Found shapes. A font only you could make.')).not.toBeInTheDocument();
    expect(document.querySelector('.mobile-workbench')).toBeInTheDocument();
    expect(document.querySelector('.mobile-workbench')?.className).toContain('max-w-[760px]');
  });

  it('keeps desktop upload-only without requesting camera access', () => {
    render(<UploadWorkbench />);
    expect(screen.queryByRole('button', { name: 'Take photo' })).not.toBeInTheDocument();
    expect(fileInputs().some((input) => input.hasAttribute('capture'))).toBe(false);
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

  it('maps mask brush pointers against the actual canvas bounds', () => {
    expect(maskCanvasPointFromClient(150, 250, { left: 100, top: 200, width: 200, height: 100 }, 20, 10)).toEqual([5, 5]);
    expect(maskCanvasPointFromClient(50, 500, { left: 100, top: 200, width: 200, height: 100 }, 20, 10)).toEqual([0, 9]);
  });

  it('shows guided source and mask preview after file selection', async () => {
    render(<UploadWorkbench />);
    const file = createTestFile();
    await userEvent.upload(uploadInput(), file);
    expect(screen.getByAltText('Source photo for A')).toBeInTheDocument();
    await waitFor(() => expect(screen.getByLabelText('Editable mask for A')).toBeInTheDocument());
    expect(URL.createObjectURL).toHaveBeenCalledWith(file);
  });

  it('keeps global threshold as the default and exposes explicit adaptive local threshold mode', async () => {
    render(<UploadWorkbench />);
    await userEvent.upload(uploadInput(), createTestFile());
    await waitFor(() => expect(screen.getByLabelText('Editable mask for A')).toBeInTheDocument());
    expandRefinementTools();
    expect(screen.getByRole('radio', { name: /Global threshold/i })).toBeChecked();
    await userEvent.click(screen.getByRole('radio', { name: /Adaptive local threshold/i }));
    expect(screen.getByRole('radio', { name: /Adaptive local threshold/i })).toBeChecked();
    expect(screen.getByRole('slider', { name: /Global threshold/i })).toBeDisabled();
    await waitFor(() => expect(screen.getByLabelText('Editable mask for A')).toBeInTheDocument());
  });

  it('collapses secondary project controls without losing edited state', async () => {
    render(<UploadWorkbench />);
    expandProjectControls();
    const projectName = screen.getByLabelText(/Project name/i);
    await userEvent.clear(projectName);
    await userEvent.type(projectName, 'Leaves test');
    const summary = screen.getByText('Project').closest('summary');
    if (!summary) throw new Error('Project summary not found.');
    await userEvent.click(summary);
    expect(screen.queryByLabelText(/Project name/i)).not.toBeInTheDocument();
    await userEvent.click(summary);
    expect(screen.getByLabelText(/Project name/i)).toHaveValue('Leaves test');
  });


  it('auto-runs ink then object candidate stages and accepts the selected mask exactly', async () => {
    let uploadedMaskText = '';
    let resolveObjects: (response: Response) => void = () => { throw new Error('objects stage did not start'); };
    const objectsResponse = new Promise<Response>((resolve) => { resolveObjects = resolve; });
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockImplementation(async (url, init) => {
      const urlStr = typeof url === 'string' ? url : url.toString();
      if (urlStr.includes('/api/uploads')) {
        const body = JSON.parse(String(init?.body ?? '{}')) as { filename?: string };
        if (body.filename?.startsWith('glyph-')) return Response.json({ ...validUploadResponse, mode: 'local', uploadUrl: '/upload-mask' });
        return Response.json(validUploadResponse);
      }
      if (urlStr === '/upload-mask') {
        uploadedMaskText = await ((init?.body as Blob | undefined)?.text() ?? Promise.resolve(''));
        return new Response(null, { status: 200 });
      }
      if (urlStr.includes('/api/capture/candidates')) {
        const body = JSON.parse(String(init?.body));
        if (body.stage === 'ink') {
          return Response.json({
            stage: 'ink',
            failures: [],
            candidates: [{ id: 'clean', label: 'Clean ink', maskDataUrl: `data:image/png;base64,${btoa('candidate-mask')}`, svgDataUrl: `data:image/svg+xml;base64,${btoa('<svg xmlns="http://www.w3.org/2000/svg"/>')}`, width: 2, height: 2, method: 'threshold-clean', warnings: [] }],
          });
        }
        return objectsResponse;
      }
      if (urlStr.endsWith('/api/jobs')) return Response.json(queuedJobResponse, { status: 202 });
      return Response.json({});
    });

    render(<UploadWorkbench />);
    await userEvent.upload(uploadInput(), createTestFile('white-a-on-black.jpg'));

    const candidate = await screen.findByTestId('candidate-option-ink-clean');
    expect(candidate).toHaveAttribute('aria-selected', 'true');
    expect(screen.getAllByText('Trying object cutouts…').length).toBeGreaterThan(0);
    await userEvent.click(screen.getByText('Accept A'));
    expect(screen.getByLabelText('B missing')).toBeInTheDocument();

    resolveObjects(Response.json({
      stage: 'objects',
      failures: [],
      candidates: [{ id: 'late-object', label: 'Late object', maskDataUrl: `data:image/png;base64,${btoa('late-mask')}`, svgDataUrl: `data:image/svg+xml;base64,${btoa('<svg xmlns="http://www.w3.org/2000/svg"/>')}`, width: 2, height: 2, method: 'efficientsam', warnings: [] }],
    }));
    await new Promise((resolve) => setTimeout(resolve, 0));
    expect(screen.queryByTestId('candidate-option-objects-late-object')).not.toBeInTheDocument();

    await userEvent.click(screen.getByText('Build guided font (1 accepted)'));
    await waitFor(() => expect(fetchMock).toHaveBeenCalledWith('/api/jobs', expect.anything()));
    expect(uploadedMaskText).toBe('candidate-mask');
  });

  it('keeps fast ink candidates when the object stage fails', async () => {
    vi.spyOn(globalThis, 'fetch').mockImplementation(async (url, init) => {
      const urlStr = typeof url === 'string' ? url : url.toString();
      if (urlStr.includes('/api/uploads')) return Response.json(validUploadResponse);
      if (urlStr.includes('/api/capture/candidates')) {
        const body = JSON.parse(String(init?.body));
        if (body.stage === 'ink') return Response.json({
          stage: 'ink',
          failures: [],
          candidates: [{ id: 'soft', label: 'Soft vector', maskDataUrl: `data:image/png;base64,${btoa('soft-mask')}`, svgDataUrl: `data:image/svg+xml;base64,${btoa('<svg xmlns="http://www.w3.org/2000/svg"/>')}`, width: 2, height: 2, method: 'threshold-soft', warnings: [] }],
        });
        return Response.json({ error: { message: 'model timed out' } }, { status: 504 });
      }
      return Response.json({});
    });

    render(<UploadWorkbench />);
    await userEvent.upload(uploadInput(), createTestFile('leaf.jpg'));
    expect(await screen.findByTestId('candidate-option-ink-soft')).toBeInTheDocument();
    await waitFor(() => expect(screen.getByText(/model timed out/i)).toBeInTheDocument());
    expect(screen.getByText('Accept A')).not.toBeDisabled();
  });

  it('does not let a stale source upload overwrite the current guided upload ref', async () => {
    let resolveFirstUpload: (response: Response) => void = () => { throw new Error('first upload not started'); };
    const firstUpload = new Promise<Response>((resolve) => { resolveFirstUpload = resolve; });
    const candidateBodies: unknown[] = [];
    vi.spyOn(globalThis, 'fetch').mockImplementation(async (url, init) => {
      const urlStr = typeof url === 'string' ? url : url.toString();
      if (urlStr.includes('/api/uploads')) {
        const body = JSON.parse(String(init?.body ?? '{}')) as { filename?: string };
        if (body.filename === 'old.jpg') return firstUpload;
        return Response.json({ ...validUploadResponse, objectKey: 'jobs/job_test/input/new.jpg' });
      }
      if (urlStr.includes('/api/capture/candidates')) {
        candidateBodies.push(JSON.parse(String(init?.body)));
        return Response.json({
          stage: 'ink',
          failures: [],
          candidates: [{ id: 'new', label: 'New file option', maskDataUrl: `data:image/png;base64,${btoa('new-mask')}`, svgDataUrl: `data:image/svg+xml;base64,${btoa('<svg xmlns="http://www.w3.org/2000/svg"/>')}`, width: 2, height: 2, method: 'threshold-clean', warnings: [] }],
        });
      }
      return Response.json({});
    });

    render(<UploadWorkbench />);
    await userEvent.upload(uploadInput(), createTestFile('old.jpg'));
    await userEvent.upload(uploadInput(), createTestFile('new.jpg'));
    resolveFirstUpload(Response.json({ ...validUploadResponse, objectKey: 'jobs/job_test/input/old.jpg' }));

    await screen.findByTestId('candidate-option-ink-new');
    expect(candidateBodies).toContainEqual(expect.objectContaining({ inputPhoto: expect.objectContaining({ objectKey: 'jobs/job_test/input/new.jpg' }) }));
    expect(candidateBodies).not.toContainEqual(expect.objectContaining({ inputPhoto: expect.objectContaining({ objectKey: 'jobs/job_test/input/old.jpg' }) }));
  });

  it('supports bounded manual mask brush edits with undo and reset', async () => {
    render(<UploadWorkbench />);
    await userEvent.upload(uploadInput(), createTestFile());
    const canvas = await screen.findByLabelText('Editable mask for A');
    await waitFor(() => expect(screen.getByText('Reset mask edits')).not.toBeDisabled());
    Object.defineProperty(canvas, 'getBoundingClientRect', { value: () => ({ left: 20, top: 30, width: 200, height: 200, right: 220, bottom: 230, x: 20, y: 30, toJSON: () => ({}) }), configurable: true });

    await userEvent.click(screen.getByLabelText(/Remove to white/i));
    fireEvent.pointerDown(canvas, { clientX: 120, clientY: 130, button: 0, pointerId: 1 });
    fireEvent.pointerUp(canvas, { clientX: 120, clientY: 130, button: 0, pointerId: 1 });
    await waitFor(() => expect(screen.getByText('Undo mask edit')).not.toBeDisabled());

    await userEvent.click(screen.getByText('Undo mask edit'));
    expect(await screen.findByText('Undid the last brush stroke.')).toBeInTheDocument();
    await userEvent.click(screen.getByText('Reset mask edits'));
    expect(await screen.findByText('Reset to the latest extracted mask.')).toBeInTheDocument();
  });

  it('accepts the edited mask PNG instead of regenerating from the source', async () => {
    let uploadedMaskText = '';
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockImplementation(async (url, init) => {
      const urlStr = typeof url === 'string' ? url : url.toString();
      if (urlStr.includes('/api/uploads')) return Response.json({ ...validUploadResponse, mode: 'local', uploadUrl: '/upload-mask' });
      if (urlStr === '/upload-mask') {
        uploadedMaskText = await ((init?.body as Blob | undefined)?.text() ?? Promise.resolve(''));
        return new Response(null, { status: 200 });
      }
      if (urlStr.endsWith('/api/jobs')) return Response.json(queuedJobResponse, { status: 202 });
      return Response.json({});
    });

    render(<UploadWorkbench />);
    await userEvent.upload(uploadInput(), createTestFile());
    const canvas = await screen.findByLabelText('Editable mask for A');
    await waitFor(() => expect(screen.getByText('Reset mask edits')).not.toBeDisabled());
    Object.defineProperty(canvas, 'getBoundingClientRect', { value: () => ({ left: 20, top: 30, width: 200, height: 200, right: 220, bottom: 230, x: 20, y: 30, toJSON: () => ({}) }), configurable: true });
    fireEvent.change(screen.getByLabelText(/Brush size/i), { target: { value: '2' } });
    fireEvent.pointerDown(canvas, { clientX: 20, clientY: 30, button: 0, pointerId: 1 });
    fireEvent.pointerUp(canvas, { clientX: 20, clientY: 30, button: 0, pointerId: 1 });
    await waitFor(() => expect(screen.getByText(/75.0% foreground/)).toBeInTheDocument());

    await userEvent.click(screen.getByText('Accept A'));
    await userEvent.click(screen.getByText('Build guided font (1 accepted)'));
    await waitFor(() => expect(fetchMock).toHaveBeenCalledWith('/api/jobs', expect.anything()));
    expect(uploadedMaskText).toContain('0,0,0,255,0,0,0,255,0,0,0,255,255,255,255,255');
  });

  it('keeps Accept disabled while an edited mask PNG encode is pending, then accepts the committed blob', async () => {
    let uploadedMaskText = '';
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockImplementation(async (url, init) => {
      const urlStr = typeof url === 'string' ? url : url.toString();
      if (urlStr.includes('/api/uploads')) return Response.json({ ...validUploadResponse, mode: 'local', uploadUrl: '/upload-mask' });
      if (urlStr === '/upload-mask') {
        uploadedMaskText = await ((init?.body as Blob | undefined)?.text() ?? Promise.resolve(''));
        return new Response(null, { status: 200 });
      }
      if (urlStr.endsWith('/api/jobs')) return Response.json(queuedJobResponse, { status: 202 });
      return Response.json({});
    });

    render(<UploadWorkbench />);
    await userEvent.upload(uploadInput(), createTestFile());
    const canvas = await screen.findByLabelText('Editable mask for A');
    await waitFor(() => expect(screen.getByText('Reset mask edits')).not.toBeDisabled());
    const encodeCallbacks: BlobCallback[] = [];
    vi.spyOn(HTMLCanvasElement.prototype, 'toBlob').mockImplementation((callback: BlobCallback) => {
      encodeCallbacks.push(callback);
    });
    Object.defineProperty(canvas, 'getBoundingClientRect', { value: () => ({ left: 20, top: 30, width: 200, height: 200, right: 220, bottom: 230, x: 20, y: 30, toJSON: () => ({}) }), configurable: true });
    fireEvent.change(screen.getByLabelText(/Brush size/i), { target: { value: '2' } });

    fireEvent.pointerDown(canvas, { clientX: 20, clientY: 30, button: 0, pointerId: 1 });
    fireEvent.pointerUp(canvas, { clientX: 20, clientY: 30, button: 0, pointerId: 1 });
    expect(screen.getByText('Accept A')).toBeDisabled();
    expect(screen.getByText(/Saving the current mask edit/)).toBeInTheDocument();
    expect(screen.getByText('Build guided font (0 accepted)')).toBeDisabled();

    expect(encodeCallbacks).toHaveLength(1);
    encodeCallbacks[0]?.(new Blob(['delayed-edited-mask'], { type: 'image/png' }));
    await waitFor(() => expect(screen.getByText('Accept A')).not.toBeDisabled());
    await userEvent.click(screen.getByText('Accept A'));
    expect(screen.getByLabelText('B missing')).toBeInTheDocument();
    await userEvent.click(screen.getByText('Build guided font (1 accepted)'));
    await waitFor(() => expect(fetchMock).toHaveBeenCalledWith('/api/jobs', expect.anything()));
    expect(uploadedMaskText).toBe('delayed-edited-mask');
  });

  it('shows an encode error and keeps Accept blocked when the edited mask PNG cannot be encoded', async () => {
    render(<UploadWorkbench />);
    await userEvent.upload(uploadInput(), createTestFile());
    const canvas = await screen.findByLabelText('Editable mask for A');
    await waitFor(() => expect(screen.getByText('Reset mask edits')).not.toBeDisabled());
    vi.spyOn(HTMLCanvasElement.prototype, 'toBlob').mockImplementation((callback: BlobCallback) => callback(null));
    Object.defineProperty(canvas, 'getBoundingClientRect', { value: () => ({ left: 20, top: 30, width: 200, height: 200, right: 220, bottom: 230, x: 20, y: 30, toJSON: () => ({}) }), configurable: true });

    fireEvent.pointerDown(canvas, { clientX: 20, clientY: 30, button: 0, pointerId: 1 });
    fireEvent.pointerUp(canvas, { clientX: 20, clientY: 30, button: 0, pointerId: 1 });

    await waitFor(() => expect(screen.getAllByText('Could not encode the edited mask PNG.').length).toBeGreaterThan(0));
    expect(screen.getByText('Accept A')).toBeDisabled();
    expect(screen.getByText('Build guided font (0 accepted)')).toBeDisabled();
  });

  it('accepts a guided glyph, advances, and retains it in the grid', async () => {
    render(<UploadWorkbench />);
    await userEvent.upload(uploadInput(), createTestFile());
    await waitFor(() => expect(screen.getByLabelText('Editable mask for A')).toBeInTheDocument());
    await userEvent.click(screen.getByText('Accept A'));
    expect(screen.getByLabelText('B missing')).toBeInTheDocument();
    expect(screen.getByText('1 accepted · 4 missing')).toBeInTheDocument();
    expect(screen.getByLabelText('A accepted')).toBeInTheDocument();
  });

  it('previous next and redo only affect the selected guided glyph', async () => {
    render(<UploadWorkbench />);
    await userEvent.upload(uploadInput(), createTestFile());
    await waitFor(() => expect(screen.getByLabelText('Editable mask for A')).toBeInTheDocument());
    await userEvent.click(screen.getByText('Accept A'));
    await userEvent.click(screen.getByText('Previous'));
    expect(screen.getByText('Redo A')).not.toBeDisabled();
    await userEvent.click(screen.getByText('Redo A'));
    expect(screen.getByLabelText('A missing')).toBeInTheDocument();
    expect(screen.getByText('0 accepted · 5 missing')).toBeInTheDocument();
  });

  it('extracts backend segmentation from the original guided source and displays actual method warnings', async () => {
    const maskDataUrl = `data:image/png;base64,${btoa('mask-png')}`;
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockImplementation(async (url) => {
      const urlStr = typeof url === 'string' ? url : url.toString();
      if (urlStr.includes('/api/uploads')) return Response.json(validUploadResponse);
      if (urlStr.includes('/api/capture/foreground')) return Response.json({ maskDataUrl, width: 2, height: 2, method: 'grabcut', warnings: ['model unavailable; used classical GrabCut'] });
      if (urlStr.endsWith('/api/jobs')) return Response.json(queuedJobResponse, { status: 202 });
      return Response.json({});
    });

    render(<UploadWorkbench />);
    await userEvent.upload(uploadInput(), createTestFile('leaf.jpg'));
    await waitFor(() => expect(screen.getByLabelText('Editable mask for A')).toBeInTheDocument());
    expandRefinementTools();
    await userEvent.click(screen.getByLabelText(/Backend segmentation cutout/i));
    expect(screen.getByText(/No browser-only model is simulated/i)).toBeInTheDocument();
    expect(screen.getByRole('slider', { name: 'Left boundary slider' })).toBeInTheDocument();
    expect(screen.getByRole('spinbutton', { name: 'Left boundary' })).toBeInTheDocument();
    await userEvent.click(screen.getByLabelText(/Classical GrabCut/i));
    await userEvent.click(screen.getByLabelText(/Interior ink/i));
    fireEvent.change(screen.getByLabelText(/Interior ink threshold/i), { target: { value: '142' } });
    await userEvent.click(screen.getByText('Extract mask'));
    await waitFor(() => expect(screen.getByText(/Segmentation ready/)).toBeInTheDocument());
    expect(screen.getAllByText(/classical GrabCut/i).length).toBeGreaterThan(0);
    expect(screen.getByText(/model unavailable; used classical GrabCut/i)).toBeInTheDocument();
    await userEvent.click(screen.getByText('Accept A'));
    await userEvent.click(screen.getByText('Build guided font (1 accepted)'));

    await waitFor(() => expect(fetchMock).toHaveBeenCalledWith('/api/jobs', expect.anything()));
    const foregroundCall = fetchMock.mock.calls.find(([url]) => String(url).includes('/api/capture/foreground'));
    const foregroundBody = JSON.parse(String((foregroundCall?.[1] as RequestInit).body));
    expect(foregroundBody).toMatchObject({
      inputPhoto: expect.objectContaining({ objectKey: validUploadResponse.objectKey }),
      rectangle: [0.12, 0.12, 0.88, 0.88],
      method: 'grabcut',
      style: 'ink',
      threshold: 142,
    });
    expect(foregroundBody.points).toBeUndefined();
    const jobsCall = fetchMock.mock.calls.find(([url]) => String(url).endsWith('/api/jobs'));
    const body = JSON.parse(String((jobsCall?.[1] as RequestInit).body)) as CreateJobRequest;
    expect(body.capture?.mode).toBe('guided');
    if (body.capture?.mode !== 'guided') throw new Error('Expected guided capture');
    expect(body.capture.glyphs[0]).toMatchObject({ char: 'A', baseline: 0.8 });
  });

  it('uses prompt points for model extraction and blocks model-only extraction without a Keep object point', async () => {
    const maskDataUrl = `data:image/png;base64,${btoa('mask-png')}`;
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockImplementation(async (url) => {
      const urlStr = typeof url === 'string' ? url : url.toString();
      if (urlStr.includes('/api/uploads')) return Response.json(validUploadResponse);
      if (urlStr.includes('/api/capture/foreground')) return Response.json({ maskDataUrl, width: 2, height: 2, method: 'slimsam', modelId: 'slimsam-test' });
      return Response.json({});
    });

    render(<UploadWorkbench />);
    await userEvent.upload(uploadInput(), createTestFile('leaf.jpg'));
    await waitFor(() => expect(screen.getByLabelText('Editable mask for A')).toBeInTheDocument());
    expandRefinementTools();
    await userEvent.click(screen.getByLabelText(/Backend segmentation cutout/i));
    await userEvent.click(screen.getByLabelText(/SlimSAM point cutout/i));
    await userEvent.click(screen.getByText('Extract mask'));
    expect(screen.getByRole('alert')).toHaveTextContent('requires at least one Keep object point');
    expect(fetchMock.mock.calls.some(([url]) => String(url).includes('/api/capture/foreground'))).toBe(false);

    const sourcePrompt = screen.getByLabelText(/Add Keep object prompt point/i);
    Object.defineProperty(sourcePrompt, 'getBoundingClientRect', { value: () => ({ left: 10, top: 20, width: 200, height: 100, right: 210, bottom: 120, x: 10, y: 20, toJSON: () => ({}) }), configurable: true });
    const sourceImage = screen.getByAltText('Source photo for A');
    Object.defineProperty(sourceImage, 'getBoundingClientRect', { value: () => ({ left: 10, top: 20, width: 200, height: 100, right: 210, bottom: 120, x: 10, y: 20, toJSON: () => ({}) }), configurable: true });
    fireEvent.click(sourcePrompt, { clientX: 110, clientY: 70 });
    await userEvent.click(screen.getByLabelText(/Exclude background/i));
    fireEvent.click(sourcePrompt, { clientX: 80, clientY: 40 });
    await userEvent.click(screen.getByText('Extract mask'));

    await waitFor(() => expect(screen.getAllByText(/AI model SlimSAM/i).length).toBeGreaterThan(0));
    const foregroundCall = fetchMock.mock.calls.find(([url]) => String(url).includes('/api/capture/foreground'));
    const foregroundBody = JSON.parse(String((foregroundCall?.[1] as RequestInit).body));
    expect(foregroundBody).toMatchObject({
      inputPhoto: expect.objectContaining({ objectKey: validUploadResponse.objectKey }),
      method: 'model',
      style: 'silhouette',
      points: [
        { x: 0.5, y: 0.5, label: 1 },
        { x: 0.35, y: 0.2, label: 0 },
      ],
    });
  });

  it('makes auto extraction without a Keep object prompt show bounded automatic fallback', async () => {
    const maskDataUrl = `data:image/png;base64,${btoa('mask-png')}`;
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockImplementation(async (url) => {
      const urlStr = typeof url === 'string' ? url : url.toString();
      if (urlStr.includes('/api/uploads')) return Response.json(validUploadResponse);
      if (urlStr.includes('/api/capture/foreground')) return Response.json({ maskDataUrl, width: 2, height: 2, method: 'grabcut' });
      return Response.json({});
    });

    render(<UploadWorkbench />);
    await userEvent.upload(uploadInput(), createTestFile('leaf.jpg'));
    await waitFor(() => expect(screen.getByLabelText('Editable mask for A')).toBeInTheDocument());
    expandRefinementTools();
    await userEvent.click(screen.getByLabelText(/Backend segmentation cutout/i));
    await userEvent.click(screen.getByText('Extract mask'));
    await waitFor(() => expect(screen.getAllByText(/automatic high-contrast extraction with a bounded classical fallback/i).length).toBeGreaterThan(0));
    const foregroundCall = fetchMock.mock.calls.find(([url]) => String(url).includes('/api/capture/foreground'));
    const foregroundBody = JSON.parse(String((foregroundCall?.[1] as RequestInit).body));
    expect(foregroundBody).toMatchObject({ method: 'grabcut', style: 'silhouette' });
    expect(foregroundBody.points).toBeUndefined();
  });

  it('uses EfficientSAM box cutout without sending retained SlimSAM points', async () => {
    const maskDataUrl = `data:image/png;base64,${btoa('mask-png')}`;
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockImplementation(async (url) => {
      const urlStr = typeof url === 'string' ? url : url.toString();
      if (urlStr.includes('/api/uploads')) return Response.json(validUploadResponse);
      if (urlStr.includes('/api/capture/foreground')) return Response.json({ maskDataUrl, width: 2, height: 2, method: 'efficientsam', modelId: 'effsam-test' });
      return Response.json({});
    });

    render(<UploadWorkbench />);
    await userEvent.upload(uploadInput(), createTestFile('leaf.jpg'));
    await waitFor(() => expect(screen.getByLabelText('Editable mask for A')).toBeInTheDocument());
    expandRefinementTools();
    await userEvent.click(screen.getByLabelText(/Backend segmentation cutout/i));
    const sourcePrompt = screen.getByLabelText(/Add Keep object prompt point/i);
    fireEvent.click(sourcePrompt, { clientX: 0, clientY: 0 });
    await userEvent.click(screen.getByLabelText(/AI box cutout/i));
    expect(screen.queryByText(/Model prompt points/i)).not.toBeInTheDocument();
    await userEvent.click(screen.getByText('Extract mask'));

    await waitFor(() => expect(screen.getAllByText(/EfficientSAM/i).length).toBeGreaterThan(0));
    const foregroundCall = fetchMock.mock.calls.find(([url]) => String(url).includes('/api/capture/foreground'));
    const foregroundBody = JSON.parse(String((foregroundCall?.[1] as RequestInit).body));
    expect(foregroundBody).toMatchObject({ method: 'box-model', style: 'silhouette' });
    expect(foregroundBody.points).toBeUndefined();

    await userEvent.click(screen.getByLabelText(/SlimSAM point cutout/i));
    expect(screen.getByText(/1 Keep object/)).toBeInTheDocument();
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
    await waitFor(() => expect(screen.getByLabelText('Editable mask for A')).toBeInTheDocument());
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

  it('serializes same-tab autosaves with the latest saved project revision', async () => {
    const user = userEvent.setup();
    const project = createProjectFixture();
    const putBodies: (ProjectPayload & { revision: number })[] = [];
    let resolveFirstSave: (response: Response) => void = () => { throw new Error('First save did not start.'); };
    vi.spyOn(globalThis, 'fetch').mockImplementation(async (url, init) => {
      const urlStr = typeof url === 'string' ? url : url.toString();
      if (urlStr === '/api/projects') return Response.json({ projects: [project] });
      if (urlStr === '/api/projects/project_1' && init?.method === 'PUT') {
        const body = JSON.parse(String(init.body)) as ProjectPayload & { revision: number };
        putBodies.push(body);
        if (putBodies.length === 1) {
          return await new Promise<Response>((resolve) => { resolveFirstSave = resolve; });
        }
        return Response.json(createProjectFixture({ ...body, revision: body.revision + 1 }));
      }
      if (urlStr === '/api/projects/project_1') return Response.json(project);
      return Response.json({});
    });

    render(<UploadWorkbench />);
    expandProjectControls();
    await user.selectOptions(await screen.findByLabelText(/Open saved project/i), 'project_1');
    await screen.findByDisplayValue('Queued Project');

    const nameInput = screen.getByLabelText(/Project name/i);
    await user.clear(nameInput);
    await user.type(nameInput, 'One');
    await waitFor(() => expect(putBodies).toHaveLength(1), { timeout: 2000 });

    await user.clear(nameInput);
    await user.type(nameInput, 'Two');
    await new Promise((resolve) => setTimeout(resolve, 900));
    expect(putBodies).toHaveLength(1);
    resolveFirstSave(Response.json(createProjectFixture({ ...putBodies[0], revision: 2 })));

    await waitFor(() => expect(putBodies).toHaveLength(2), { timeout: 2000 });
    expect(putBodies[0].revision).toBe(1);
    expect(putBodies[1].revision).toBe(2);
    expect(putBodies[1].name).toBe('Two');
  });

  it('blocks project switching while an autosave is in flight so queued edits cannot write another project', async () => {
    const user = userEvent.setup();
    const projectOne = createProjectFixture({ id: 'project_1', name: 'Project One' });
    const projectTwo = createProjectFixture({ id: 'project_2', name: 'Project Two' });
    const putUrls: string[] = [];
    let resolveFirstSave: (response: Response) => void = () => { throw new Error('First save did not start.'); };
    vi.spyOn(globalThis, 'fetch').mockImplementation(async (url, init) => {
      const urlStr = typeof url === 'string' ? url : url.toString();
      if (urlStr === '/api/projects') return Response.json({ projects: [projectOne, projectTwo] });
      if (urlStr === '/api/projects/project_1' && init?.method === 'PUT') {
        putUrls.push(urlStr);
        return await new Promise<Response>((resolve) => { resolveFirstSave = resolve; });
      }
      if (urlStr === '/api/projects/project_2' && init?.method === 'PUT') {
        putUrls.push(urlStr);
        return Response.json(projectTwo);
      }
      if (urlStr === '/api/projects/project_1') return Response.json(projectOne);
      if (urlStr === '/api/projects/project_2') return Response.json(projectTwo);
      return Response.json({});
    });

    render(<UploadWorkbench />);
    expandProjectControls();
    await user.selectOptions(await screen.findByLabelText(/Open saved project/i), 'project_1');
    await screen.findByDisplayValue('Project One');
    const nameInput = screen.getByLabelText(/Project name/i);
    await user.clear(nameInput);
    await user.type(nameInput, 'One edit');
    await waitFor(() => expect(putUrls).toEqual(['/api/projects/project_1']), { timeout: 2000 });
    await user.clear(nameInput);
    await user.type(nameInput, 'Queued old edit');
    await new Promise((resolve) => setTimeout(resolve, 900));
    expandProjectControls();
    expect(screen.getByLabelText(/Open saved project/i)).toBeDisabled();
    resolveFirstSave(Response.json(createProjectFixture({ id: 'project_1', name: 'One edit', revision: 2 })));
    await new Promise((resolve) => setTimeout(resolve, 300));
    expect(putUrls.every((url) => url === '/api/projects/project_1')).toBe(true);
    expect(putUrls).not.toContain('/api/projects/project_2');
  });

  it('cancels pending autosave work on unmount', async () => {
    const project = createProjectFixture();
    const putCalls: RequestInit[] = [];
    vi.spyOn(globalThis, 'fetch').mockImplementation(async (url, init) => {
      const urlStr = typeof url === 'string' ? url : url.toString();
      if (urlStr === '/api/projects') return Response.json({ projects: [project] });
      if (urlStr === '/api/projects/project_1' && init?.method === 'PUT') {
        putCalls.push(init);
        return Response.json(createProjectFixture({ revision: 2 }));
      }
      if (urlStr === '/api/projects/project_1') return Response.json(project);
      return Response.json({});
    });

    const rendered = render(<UploadWorkbench />);
    expandProjectControls();
    await userEvent.selectOptions(await screen.findByLabelText(/Open saved project/i), 'project_1');
    await screen.findByDisplayValue('Queued Project');
    await userEvent.clear(screen.getByLabelText(/Project name/i));
    await userEvent.type(screen.getByLabelText(/Project name/i), 'Unmounted edit');
    rendered.unmount();
    await new Promise((resolve) => setTimeout(resolve, 900));
    expect(putCalls).toHaveLength(0);
  });

  it('keeps the current workspace when creating a new project fails', async () => {
    vi.spyOn(globalThis, 'fetch').mockImplementation(async (url, init) => {
      const urlStr = typeof url === 'string' ? url : url.toString();
      if (urlStr === '/api/projects' && init?.method === 'POST') return Response.json({ error: { message: 'Quota exceeded.' } }, { status: 500 });
      if (urlStr === '/api/projects') return Response.json({ projects: [] });
      return Response.json({});
    });

    render(<UploadWorkbench />);
    await userEvent.upload(uploadInput(), createTestFile());
    await waitFor(() => expect(screen.getByLabelText('Editable mask for A')).toBeInTheDocument());
    await userEvent.click(screen.getByText('Accept A'));
    expandProjectControls();
    await userEvent.click(screen.getByText('New project'));
    await screen.findByText(/Quota exceeded/i);
    expect(screen.getByLabelText('A accepted')).toBeInTheDocument();
  });

  it('keeps current work and blocks autosave when saved project mask hydration fails', async () => {
    const project = createProjectFixture({
      id: 'project_bad',
      name: 'Broken remote project',
      glyphs: [{
        char: 'B',
        inputPhoto: { objectKey: 'projects/project_bad/B.png', bucket: 'test-bucket', contentType: 'image/png', sizeBytes: 12 },
        baseline: 0.75,
        scale: 1,
        spacing: 0,
        width: 2,
        height: 2,
        foregroundRatio: 0.5,
        filename: 'B.png',
      }],
    });
    const putCalls: RequestInit[] = [];
    vi.spyOn(globalThis, 'fetch').mockImplementation(async (url, init) => {
      const urlStr = typeof url === 'string' ? url : url.toString();
      if (urlStr === '/api/projects') return Response.json({ projects: [project] });
      if (urlStr === '/api/projects/project_bad' && init?.method === 'PUT') {
        putCalls.push(init);
        return Response.json(project);
      }
      if (urlStr === '/api/projects/project_bad') return Response.json(project);
      if (urlStr.includes('/api/objects/projects/project_bad/B.png')) return new Response('missing', { status: 404 });
      return Response.json({});
    });

    render(<UploadWorkbench />);
    await userEvent.upload(uploadInput(), createTestFile());
    await waitFor(() => expect(screen.getByLabelText('Editable mask for A')).toBeInTheDocument());
    await userEvent.click(screen.getByText('Accept A'));
    expect(screen.getByLabelText('A accepted')).toBeInTheDocument();

    expandProjectControls();
    await userEvent.selectOptions(await screen.findByLabelText(/Open saved project/i), 'project_bad');
    await screen.findByText('Could not restore an accepted mask PNG from the saved project.');
    expect(screen.getByLabelText('A accepted')).toBeInTheDocument();
    await new Promise((resolve) => setTimeout(resolve, 900));
    expect(putCalls).toHaveLength(0);
  });

  it('autosaves selected markerless sheet uploads as sheet refs without guided glyph payloads', async () => {
    const project = createProjectFixture();
    let savedBody: (ProjectPayload & { revision: number }) | null = null;
    vi.spyOn(globalThis, 'fetch').mockImplementation(async (url, init) => {
      const urlStr = typeof url === 'string' ? url : url.toString();
      if (urlStr === '/api/projects') return Response.json({ projects: [project] });
      if (urlStr.includes('/api/uploads')) return Response.json(validUploadResponse);
      if (urlStr === '/api/projects/project_1' && init?.method === 'PUT') {
        savedBody = JSON.parse(String(init.body)) as ProjectPayload & { revision: number };
        return Response.json(createProjectFixture({ ...savedBody, revision: savedBody.revision + 1 }));
      }
      if (urlStr === '/api/projects/project_1') return Response.json(project);
      return Response.json({});
    });

    render(<UploadWorkbench />);
    expandProjectControls();
    await userEvent.selectOptions(await screen.findByLabelText(/Open saved project/i), 'project_1');
    await screen.findByDisplayValue('Queued Project');
    await userEvent.click(screen.getByRole('tab', { name: /Markerless A4 sheet/i }));
    await userEvent.upload(uploadInput(), createTestFile('sheet.jpg'));
    await userEvent.click(screen.getByText('Confirm page corners'));

    await waitFor(() => expect(savedBody).not.toBeNull(), { timeout: 2500 });
    expect(savedBody).toMatchObject({
      mode: 'markerless',
      glyphs: [],
      sheet: { inputPhoto: expect.objectContaining({ objectKey: validUploadResponse.objectKey }), cornersConfirmed: true },
    });
  });

  it('does not save an old sheet upload after the user replaces that sheet', async () => {
    const project = createProjectFixture();
    const savedKeys: string[] = [];
    let finishOldUpload!: (response: Response) => void;
    let oldUploadStarted = false;
    vi.spyOn(globalThis, 'fetch').mockImplementation(async (url, init) => {
      const address = String(url);
      if (address === '/api/projects') return Response.json({ projects: [project] });
      if (address === '/api/uploads') {
        const body = JSON.parse(String(init?.body));
        if (body.filename === 'old.jpg') {
          oldUploadStarted = true;
          return await new Promise<Response>(resolve => { finishOldUpload = resolve; });
        }
        return Response.json({ ...validUploadResponse, objectKey: 'uploads/new.jpg' });
      }
      if (address === '/api/projects/project_1' && init?.method === 'PUT') {
        const body = JSON.parse(String(init.body));
        if (body.sheet) savedKeys.push(body.sheet.inputPhoto.objectKey);
        return Response.json(createProjectFixture({ ...body, revision: body.revision + 1 }));
      }
      if (address === '/api/projects/project_1') return Response.json(project);
      return Response.json({});
    });
    render(<UploadWorkbench />);
    expandProjectControls();
    await userEvent.selectOptions(await screen.findByLabelText(/Open saved project/i), 'project_1');
    await screen.findByDisplayValue('Queued Project');
    await userEvent.click(screen.getByRole('tab', { name: /Markerless A4 sheet/i }));
    await userEvent.upload(uploadInput(), createTestFile('old.jpg'));
    await waitFor(() => expect(oldUploadStarted).toBe(true), { timeout: 2000 });
    await userEvent.click(screen.getByRole('button', { name: 'Remove photo' }));
    await userEvent.upload(uploadInput(), createTestFile('new.jpg'));
    finishOldUpload(Response.json({ ...validUploadResponse, objectKey: 'uploads/old.jpg' }));
    await waitFor(() => expect(savedKeys).toContain('uploads/new.jpg'), { timeout: 2500 });
    expect(savedKeys).not.toContain('uploads/old.jpg');
  });

  it('restores markerless sheet previews and builds from the saved sheet ref without reuploading', async () => {
    const savedSheetRef = { objectKey: 'projects/project_sheet/sheet.png', bucket: 'test-bucket', contentType: 'image/png', sizeBytes: 12 };
    const project = createProjectFixture({
      id: 'project_sheet',
      name: 'Saved sheet project',
      mode: 'markerless',
      sheet: { inputPhoto: savedSheetRef, corners: [[0.1, 0.1], [0.9, 0.1], [0.9, 0.9], [0.1, 0.9]], cornersConfirmed: true },
    });
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockImplementation(async (url) => {
      const urlStr = typeof url === 'string' ? url : url.toString();
      if (urlStr === '/api/projects') return Response.json({ projects: [project] });
      if (urlStr === '/api/projects/project_sheet') return Response.json(project);
      if (urlStr.includes('/api/objects/projects/project_sheet/sheet.png')) return new Response(new Blob(['sheet'], { type: 'image/png' }));
      if (urlStr.endsWith('/api/jobs')) return Response.json(queuedJobResponse, { status: 202 });
      return Response.json({});
    });

    render(<UploadWorkbench />);
    expandProjectControls();
    await userEvent.selectOptions(await screen.findByLabelText(/Open saved project/i), 'project_sheet');
    await screen.findByAltText('Captured markerless A4 sheet preview');
    expect(screen.getByText('Confirmed for job submission.')).toBeInTheDocument();
    await userEvent.click(screen.getByText('Build markerless sheet font'));
    await waitFor(() => expect(fetchMock).toHaveBeenCalledWith('/api/jobs', expect.anything()));
    expect(fetchMock.mock.calls.some(([url]) => String(url).includes('/api/uploads'))).toBe(false);
    const jobsCall = fetchMock.mock.calls.find(([url]) => String(url).endsWith('/api/jobs'));
    const body = JSON.parse(String((jobsCall?.[1] as RequestInit).body)) as CreateJobRequest;
    expect(body.inputPhoto).toMatchObject(savedSheetRef);
    expect(body.capture?.mode).toBe('template');
  });

  it('restores legacy sheet previews and builds from the saved sheet ref without reuploading', async () => {
    const savedSheetRef = { objectKey: 'projects/project_legacy/template.png', bucket: 'test-bucket', contentType: 'image/png', sizeBytes: 12 };
    const project = createProjectFixture({
      id: 'project_legacy',
      name: 'Saved legacy project',
      mode: 'legacy',
      sheet: { inputPhoto: savedSheetRef },
    });
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockImplementation(async (url) => {
      const urlStr = typeof url === 'string' ? url : url.toString();
      if (urlStr === '/api/projects') return Response.json({ projects: [project] });
      if (urlStr === '/api/projects/project_legacy') return Response.json(project);
      if (urlStr.includes('/api/objects/projects/project_legacy/template.png')) return new Response(new Blob(['legacy'], { type: 'image/png' }));
      if (urlStr.endsWith('/api/jobs')) return Response.json(queuedJobResponse, { status: 202 });
      return Response.json({});
    });

    render(<UploadWorkbench />);
    expandProjectControls();
    await userEvent.selectOptions(await screen.findByLabelText(/Open saved project/i), 'project_legacy');
    await screen.findByAltText('Captured template preview');
    await userEvent.click(screen.getByText('Build legacy marker font'));
    await waitFor(() => expect(fetchMock).toHaveBeenCalledWith('/api/jobs', expect.anything()));
    expect(fetchMock.mock.calls.some(([url]) => String(url).includes('/api/uploads'))).toBe(false);
    const jobsCall = fetchMock.mock.calls.find(([url]) => String(url).endsWith('/api/jobs'));
    const body = JSON.parse(String((jobsCall?.[1] as RequestInit).body)) as CreateJobRequest;
    expect(body.inputPhoto).toMatchObject(savedSheetRef);
    expect(body.capture).toBeUndefined();
  });

  it('switches to markerless sheet mode and requires confirmed corners', async () => {
    render(<UploadWorkbench />);
    await userEvent.click(screen.getByRole('tab', { name: /Markerless A4 sheet/i }));
    await userEvent.upload(uploadInput(), createTestFile('sheet.jpg'));
    expect(screen.getByText('Build markerless sheet font')).toBeDisabled();
    await userEvent.click(screen.getByText('Confirm page corners'));
    expect(screen.getByText('Confirmed for job submission.')).toBeInTheDocument();
  });


  it('ignores stale automatic page-corner suggestions after manual corner edits', async () => {
    let finishDetection!: (response: Response) => void;
    vi.spyOn(globalThis, 'fetch').mockImplementation(async (url) => {
      const urlStr = typeof url === 'string' ? url : url.toString();
      if (urlStr.includes('/api/uploads')) return Response.json(validUploadResponse);
      if (urlStr === '/api/capture/page') {
        return await new Promise<Response>((resolve) => { finishDetection = resolve; });
      }
      return Response.json({});
    });

    render(<UploadWorkbench />);
    await userEvent.click(screen.getByRole('tab', { name: /Markerless A4 sheet/i }));
    await userEvent.upload(uploadInput(), createTestFile('sheet.jpg'));
    await userEvent.click(screen.getByRole('button', { name: 'Find corners' }));
    await screen.findByText('Asking the Python worker for page-corner suggestions…');

    fireEvent.change(screen.getAllByLabelText('x')[0], { target: { value: '0.234' } });
    expect(screen.getByDisplayValue('0.234')).toBeInTheDocument();

    finishDetection(Response.json({ corners: [[0.7, 0.7], [0.8, 0.7], [0.8, 0.8], [0.7, 0.8]] }));

    await waitFor(() => expect(screen.getByRole('button', { name: 'Find corners' })).not.toBeDisabled());
    expect(screen.getByDisplayValue('0.234')).toBeInTheDocument();
    expect(screen.queryByText('Corner suggestions loaded. Confirm them or adjust TL/TR/BR/BL before building.')).not.toBeInTheDocument();
  });

  it('ignores stale automatic page-corner suggestions after replacing the sheet', async () => {
    let finishDetection!: (response: Response) => void;
    vi.spyOn(globalThis, 'fetch').mockImplementation(async (url) => {
      const urlStr = typeof url === 'string' ? url : url.toString();
      if (urlStr.includes('/api/uploads')) return Response.json(validUploadResponse);
      if (urlStr === '/api/capture/page') {
        return await new Promise<Response>((resolve) => { finishDetection = resolve; });
      }
      return Response.json({});
    });

    render(<UploadWorkbench />);
    await userEvent.click(screen.getByRole('tab', { name: /Markerless A4 sheet/i }));
    await userEvent.upload(uploadInput(), createTestFile('old-sheet.jpg'));
    await userEvent.click(screen.getByRole('button', { name: 'Find corners' }));
    await screen.findByText('Asking the Python worker for page-corner suggestions…');

    await userEvent.click(screen.getByRole('button', { name: 'Remove photo' }));
    await userEvent.upload(uploadInput(), createTestFile('new-sheet.jpg'));
    expect(screen.getAllByLabelText('x')[0]).toHaveValue(0.08);

    finishDetection(Response.json({ corners: [[0.7, 0.7], [0.8, 0.7], [0.8, 0.8], [0.7, 0.8]] }));

    await waitFor(() => expect(screen.getByRole('button', { name: 'Find corners' })).not.toBeDisabled());
    expect(screen.getAllByLabelText('x')[0]).toHaveValue(0.08);
    expect(screen.queryByText('Corner suggestions loaded. Confirm them or adjust TL/TR/BR/BL before building.')).not.toBeInTheDocument();
  });

  it('ignores stale automatic page-corner suggestions after switching capture modes', async () => {
    let finishDetection!: (response: Response) => void;
    vi.spyOn(globalThis, 'fetch').mockImplementation(async (url) => {
      const urlStr = typeof url === 'string' ? url : url.toString();
      if (urlStr.includes('/api/uploads')) return Response.json(validUploadResponse);
      if (urlStr === '/api/capture/page') {
        return await new Promise<Response>((resolve) => { finishDetection = resolve; });
      }
      return Response.json({});
    });

    render(<UploadWorkbench />);
    await userEvent.click(screen.getByRole('tab', { name: /Markerless A4 sheet/i }));
    await userEvent.upload(uploadInput(), createTestFile('sheet.jpg'));
    await userEvent.click(screen.getByRole('button', { name: 'Find corners' }));
    await screen.findByText('Asking the Python worker for page-corner suggestions…');

    await userEvent.click(screen.getByRole('tab', { name: /Guided characters/i }));
    finishDetection(Response.json({ corners: [[0.7, 0.7], [0.8, 0.7], [0.8, 0.8], [0.7, 0.8]] }));
    await waitFor(() => expect(screen.getByRole('tab', { name: /Guided characters/i })).toHaveAttribute('aria-selected', 'true'));

    await userEvent.click(screen.getByRole('tab', { name: /Markerless A4 sheet/i }));
    expect(screen.getAllByLabelText('x')[0]).toHaveValue(0.08);
    expect(screen.queryByText('Corner suggestions loaded. Confirm them or adjust TL/TR/BR/BL before building.')).not.toBeInTheDocument();
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
    await waitFor(() => expect(screen.getByLabelText('Editable mask for A')).toBeInTheDocument());
    await userEvent.click(screen.getByText('Accept A'));
    expandFontSettings();
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
    await waitFor(() => expect(screen.getByLabelText('Editable mask for A')).toBeInTheDocument());
    await userEvent.click(screen.getByText('Accept A'));
    await userEvent.click(screen.getByText('Build guided font (1 accepted)'));

    expandProjectControls();
    expect(screen.getByLabelText(/Open saved project/i)).toBeDisabled();
    await waitFor(() => expect(screen.getByText('Complete')).toBeInTheDocument(), { timeout: 10000 });
    expect(screen.getByText('OpenType Font')).toBeInTheDocument();
    expect(screen.getByText('TrueType Font')).toBeInTheDocument();
    expect(screen.getByText('Typed proof from generated TTF')).toBeInTheDocument();
    expect(screen.getByDisplayValue('A')).toBeInTheDocument();
    expect(screen.getByText(/How to install/)).toBeInTheDocument();
  });


  it('deduplicates completed job keyed children when the same succeeded job is observed again', async () => {
    let pollCount = 0;
    const consoleError = vi.spyOn(console, 'error').mockImplementation(() => undefined);
    vi.spyOn(globalThis, 'fetch').mockImplementation(async (url) => {
      const urlStr = typeof url === 'string' ? url : url.toString();
      if (urlStr.includes('/api/uploads')) return Response.json(validUploadResponse);
      if (urlStr.includes('/api/jobs/') && !urlStr.endsWith('/api/jobs')) {
        pollCount++;
        return Response.json({ ...succeededJobResponse, progressLabel: `Font build complete ${pollCount}` });
      }
      if (urlStr.endsWith('/api/jobs')) return Response.json(queuedJobResponse, { status: 202 });
      return Response.json({});
    });
    vi.stubGlobal('FontFace', class { constructor(public family: string) {} async load() { return this; } });
    Object.defineProperty(document, 'fonts', { value: { add: vi.fn() }, configurable: true });

    render(<UploadWorkbench allowDelete />);
    await userEvent.upload(uploadInput(), createTestFile());
    await waitFor(() => expect(screen.getByLabelText('Editable mask for A')).toBeInTheDocument());
    await userEvent.click(screen.getByText('Accept A'));
    await userEvent.click(screen.getByText('Build guided font (1 accepted)'));

    await waitFor(() => expect(screen.getByText('Complete')).toBeInTheDocument(), { timeout: 10000 });
    expect(screen.getByText('Typed proof from generated TTF')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Delete this job and files/i })).toBeInTheDocument();

    await userEvent.click(screen.getByText('Build guided font (1 accepted)'));
    await waitFor(() => expect(pollCount).toBe(2), { timeout: 10000 });
    expect(screen.getAllByRole('button', { name: /Delete this job and files/i })).toHaveLength(1);
    expect(consoleError.mock.calls.flat().join('\n')).not.toContain('Encountered two children with the same key');
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
    await waitFor(() => expect(screen.getByLabelText('Editable mask for A')).toBeInTheDocument());
    await userEvent.click(screen.getByText('Accept A'));
    await userEvent.click(screen.getByText('Build guided font (1 accepted)'));

    await waitFor(() => expect(screen.getByText('Failed')).toBeInTheDocument(), { timeout: 10000 });
    expect(screen.getByText('MARKER_NOT_FOUND')).toBeInTheDocument();
  });

  it('shows ready status when no job is active', () => {
    render(<UploadWorkbench />);
    expect(screen.getByText('Ready')).toBeInTheDocument();
    expect(screen.getByText('Your font preview will appear here. Add a character and build your font.')).toBeInTheDocument();
  });
});
