import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { MobileCameraButton, isMobileCaptureDevice } from '../capture/mobile-camera';

type MockTrack = MediaStreamTrack & { stop: ReturnType<typeof vi.fn> };
type MockStream = MediaStream & { track: MockTrack };

function makeStream(deviceId = 'rear-1') {
  const track = {
    stop: vi.fn(),
    getSettings: () => ({ deviceId }),
  } as unknown as MockTrack;
  return {
    track,
    getTracks: () => [track],
    getVideoTracks: () => [track],
  } as unknown as MockStream;
}

function mockMatchMedia(matches: boolean) {
  const state = { matches };
  const listeners = new Set<(event: MediaQueryListEvent) => void>();
  vi.stubGlobal('matchMedia', vi.fn((query: string) => ({
    media: query,
    get matches() { return state.matches; },
    onchange: null,
    addEventListener: (_event: 'change', listener: (event: MediaQueryListEvent) => void) => listeners.add(listener),
    removeEventListener: (_event: 'change', listener: (event: MediaQueryListEvent) => void) => listeners.delete(listener),
    addListener: vi.fn(),
    removeListener: vi.fn(),
    dispatchEvent: vi.fn(),
  })));
  return {
    setMatches(nextMatches: boolean) {
      state.matches = nextMatches;
      listeners.forEach((listener) => listener({ matches: nextMatches } as MediaQueryListEvent));
    },
  };
}

function mockNavigatorMedia(mediaDevices: Partial<MediaDevices>, userAgent = 'Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) Mobile') {
  Object.defineProperty(window.navigator, 'mediaDevices', { value: mediaDevices, configurable: true });
  Object.defineProperty(window.navigator, 'userAgent', { value: userAgent, configurable: true });
}

function mockSecureContext(value = true) {
  Object.defineProperty(window, 'isSecureContext', { value, configurable: true });
}

function mockVideoAndCanvas() {
  vi.spyOn(HTMLMediaElement.prototype, 'play').mockResolvedValue(undefined);
  vi.spyOn(HTMLCanvasElement.prototype, 'getContext').mockReturnValue({ drawImage: vi.fn() } as unknown as CanvasRenderingContext2D);
  vi.spyOn(HTMLCanvasElement.prototype, 'toBlob').mockImplementation(function toBlob(callback: BlobCallback) {
    callback(new Blob(['jpeg-bytes'], { type: 'image/jpeg' }));
  });
}

function markVideoReady(width = 4032, height = 3024) {
  const video = screen.getByLabelText('Live camera preview') as HTMLVideoElement;
  Object.defineProperty(video, 'videoWidth', { value: width, configurable: true });
  Object.defineProperty(video, 'videoHeight', { value: height, configurable: true });
  Object.defineProperty(video, 'readyState', { value: 2, configurable: true });
  fireEvent.loadedData(video);
  return video;
}

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason?: unknown) => void;
  const promise = new Promise<T>((res, rej) => { resolve = res; reject = rej; });
  return { promise, resolve, reject };
}

describe('MobileCameraButton', () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    mockSecureContext(true);
    mockMatchMedia(true);
    mockVideoAndCanvas();
  });

  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
  });

  it('uses coarse pointer or mobile user agent detection instead of narrow desktop width', () => {
    mockMatchMedia(false);
    mockNavigatorMedia({}, 'Mozilla/5.0 (Macintosh; Intel Mac OS X 15_0) AppleWebKit/605.1 Safari/605.1');
    expect(isMobileCaptureDevice()).toBe(false);
    mockNavigatorMedia({}, 'Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) Mobile');
    expect(isMobileCaptureDevice()).toBe(true);
  });

  it('hides the capture button on desktop and does not request camera access', async () => {
    mockMatchMedia(false);
    const getUserMedia = vi.fn();
    mockNavigatorMedia({ getUserMedia: getUserMedia as unknown as MediaDevices['getUserMedia'] }, 'Mozilla/5.0 (Macintosh; Intel Mac OS X 15_0)');

    render(<MobileCameraButton onCapture={vi.fn()} />);

    await waitFor(() => expect(screen.queryByRole('button', { name: 'Take photo' })).not.toBeInTheDocument());
    expect(getUserMedia).not.toHaveBeenCalled();
    expect(document.querySelector('input[type="file"]')).not.toBeInTheDocument();
  });

  it('opens the rear camera only after a tap and captures a bounded JPEG file', async () => {
    const stream = makeStream('rear-1');
    const getUserMedia = vi.fn().mockResolvedValue(stream);
    const enumerateDevices = vi.fn().mockResolvedValue([{ kind: 'videoinput', deviceId: 'rear-1', label: 'Back Camera' }]);
    mockNavigatorMedia({ getUserMedia, enumerateDevices } as unknown as MediaDevices);
    const onCapture = vi.fn();

    const createdCanvases: HTMLCanvasElement[] = [];
    const originalCreateElement = document.createElement.bind(document);
    vi.spyOn(document, 'createElement').mockImplementation(((tagName: string, options?: ElementCreationOptions) => {
      const element = originalCreateElement(tagName, options);
      if (tagName.toLowerCase() === 'canvas') createdCanvases.push(element as HTMLCanvasElement);
      return element;
    }) as typeof document.createElement);

    render(<MobileCameraButton onCapture={onCapture} />);
    const button = await screen.findByRole('button', { name: 'Take photo' });
    expect(getUserMedia).not.toHaveBeenCalled();

    await userEvent.click(button);
    expect(getUserMedia).toHaveBeenCalledWith({
      audio: false,
      video: { facingMode: { ideal: 'environment' }, width: { ideal: 1920 }, height: { ideal: 1440 } },
    });
    expect(await screen.findByRole('dialog', { name: 'Phone camera' })).toBeInTheDocument();
    markVideoReady();
    await userEvent.click(screen.getByRole('button', { name: 'Capture photo' }));

    await waitFor(() => expect(onCapture).toHaveBeenCalledWith(expect.any(File)));
    const file = onCapture.mock.calls[0][0] as File;
    expect(file.name).toMatch(/^camera-\d+\.jpg$/);
    expect(file.type).toBe('image/jpeg');
    expect(createdCanvases).toHaveLength(1);
    expect(Math.max(createdCanvases[0].width, createdCanvases[0].height)).toBeLessThanOrEqual(2560);
    expect(stream.track.stop).toHaveBeenCalledTimes(1);
    expect(screen.queryByRole('dialog', { name: 'Phone camera' })).not.toBeInTheDocument();
  });

  it('shows permission denial copy and keeps the mobile phone picker fallback', async () => {
    const getUserMedia = vi.fn().mockRejectedValue(new DOMException('denied', 'NotAllowedError'));
    mockNavigatorMedia({ getUserMedia } as unknown as MediaDevices);

    render(<MobileCameraButton onCapture={vi.fn()} />);
    await userEvent.click(await screen.findByRole('button', { name: 'Take photo' }));

    expect(await screen.findByRole('alert')).toHaveTextContent('Camera permission was blocked');
    expect(screen.getByRole('button', { name: 'Use phone picker' })).toBeInTheDocument();
    const fallback = document.querySelector('input[type="file"]') as HTMLInputElement;
    expect(fallback).toHaveAttribute('capture', 'environment');
    expect(fallback.getAttribute('accept')).toContain('image/jpeg');
    expect(fallback.getAttribute('accept')).toContain('image/png');
    expect(fallback.getAttribute('accept')).toContain('image/webp');
  });



  it('closes and stops the stream if the device no longer reports mobile camera capability', async () => {
    const pointer = mockMatchMedia(true);
    const stream = makeStream('rear-1');
    mockNavigatorMedia({ getUserMedia: vi.fn().mockResolvedValue(stream) } as unknown as MediaDevices, 'Mozilla/5.0 (Macintosh; Intel Mac OS X 15_0)');

    render(<MobileCameraButton onCapture={vi.fn()} />);
    await userEvent.click(await screen.findByRole('button', { name: 'Take photo' }));
    await screen.findByRole('dialog', { name: 'Phone camera' });

    pointer.setMatches(false);

    await waitFor(() => expect(stream.track.stop).toHaveBeenCalledTimes(1));
    expect(screen.queryByRole('dialog', { name: 'Phone camera' })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Take photo' })).not.toBeInTheDocument();
  });

  it('stops the live stream before opening the native phone picker fallback', async () => {
    const stream = makeStream('rear-1');
    const getUserMedia = vi.fn().mockResolvedValue(stream);
    mockNavigatorMedia({ getUserMedia } as unknown as MediaDevices);

    render(<MobileCameraButton onCapture={vi.fn()} />);
    await userEvent.click(await screen.findByRole('button', { name: 'Take photo' }));
    await screen.findByRole('dialog', { name: 'Phone camera' });
    const fallback = document.querySelector('input[type="file"]') as HTMLInputElement;
    const clickFallback = vi.spyOn(fallback, 'click').mockImplementation(() => undefined);

    await userEvent.click(screen.getByRole('button', { name: 'Use phone picker' }));

    expect(stream.track.stop).toHaveBeenCalledTimes(1);
    expect(clickFallback).toHaveBeenCalledTimes(1);
    expect(screen.queryByRole('dialog', { name: 'Phone camera' })).not.toBeInTheDocument();
    expect(fallback).toHaveAttribute('capture', 'environment');
  });


  it('does not deliver a deferred canvas capture after the camera dialog is closed', async () => {
    const stream = makeStream('rear-1');
    mockNavigatorMedia({ getUserMedia: vi.fn().mockResolvedValue(stream) } as unknown as MediaDevices);
    let resolveBlob!: (blob: Blob | null) => void;
    vi.spyOn(HTMLCanvasElement.prototype, 'toBlob').mockImplementation(function toBlob(callback: BlobCallback) {
      resolveBlob = callback;
    });
    const onCapture = vi.fn();

    render(<MobileCameraButton onCapture={onCapture} />);
    await userEvent.click(await screen.findByRole('button', { name: 'Take photo' }));
    markVideoReady();
    await userEvent.click(screen.getByRole('button', { name: 'Capture photo' }));
    await userEvent.click(screen.getByRole('button', { name: 'Close camera' }));

    resolveBlob(new Blob(['late-jpeg'], { type: 'image/jpeg' }));

    await waitFor(() => expect(stream.track.stop).toHaveBeenCalledTimes(1));
    expect(onCapture).not.toHaveBeenCalled();
  });

  it('stops a pending getUserMedia stream that resolves after unmount', async () => {
    const late = deferred<MediaStream>();
    const stream = makeStream('rear-after-unmount');
    mockNavigatorMedia({ getUserMedia: vi.fn().mockReturnValue(late.promise) } as unknown as MediaDevices);

    const view = render(<MobileCameraButton onCapture={vi.fn()} />);
    await userEvent.click(await screen.findByRole('button', { name: 'Take photo' }));
    view.unmount();
    late.resolve(stream);

    await waitFor(() => expect(stream.track.stop).toHaveBeenCalledTimes(1));
  });

  it('stops a late-resolved stream after the dialog is closed', async () => {
    const late = deferred<MediaStream>();
    const stream = makeStream('rear-late');
    const getUserMedia = vi.fn().mockReturnValue(late.promise);
    mockNavigatorMedia({ getUserMedia } as unknown as MediaDevices);

    render(<MobileCameraButton onCapture={vi.fn()} />);
    await userEvent.click(await screen.findByRole('button', { name: 'Take photo' }));
    await userEvent.click(await screen.findByRole('button', { name: 'Close camera' }));
    late.resolve(stream);

    await waitFor(() => expect(stream.track.stop).toHaveBeenCalledTimes(1));
  });

  it('switches cameras by exact deviceId and stops active streams when hidden', async () => {
    const first = makeStream('rear-1');
    const second = makeStream('wide-2');
    const getUserMedia = vi.fn()
      .mockResolvedValueOnce(first)
      .mockResolvedValueOnce(second);
    const enumerateDevices = vi.fn().mockResolvedValue([
      { kind: 'videoinput', deviceId: 'rear-1', label: 'Back Camera' },
      { kind: 'videoinput', deviceId: 'wide-2', label: '' },
    ]);
    mockNavigatorMedia({ getUserMedia, enumerateDevices } as unknown as MediaDevices);

    render(<MobileCameraButton onCapture={vi.fn()} />);
    await userEvent.click(await screen.findByRole('button', { name: 'Take photo' }));
    const dialog = await screen.findByRole('dialog', { name: 'Phone camera' });
    const selector = await within(dialog).findByLabelText('Camera');
    expect(within(dialog).getByRole('option', { name: 'Back Camera' })).toBeInTheDocument();
    expect(within(dialog).getByRole('option', { name: 'Camera 2' })).toBeInTheDocument();

    await userEvent.selectOptions(selector, 'wide-2');
    expect(first.track.stop).toHaveBeenCalledTimes(1);
    expect(getUserMedia).toHaveBeenLastCalledWith({
      audio: false,
      video: { deviceId: { exact: 'wide-2' }, width: { ideal: 1920 }, height: { ideal: 1440 } },
    });

    await waitFor(() => expect(screen.getByRole('status')).toHaveTextContent('Camera ready'));
    Object.defineProperty(document, 'visibilityState', { value: 'hidden', configurable: true });
    fireEvent(document, new Event('visibilitychange'));

    await waitFor(() => expect(second.track.stop).toHaveBeenCalledTimes(1));
    expect(screen.queryByRole('dialog', { name: 'Phone camera' })).not.toBeInTheDocument();
  });
});
