'use client';

import { ChangeEvent, useCallback, useEffect, useId, useRef, useState } from 'react';

export type MobileCameraButtonProps = {
  onCapture: (file: File) => void;
  label?: string;
  className?: string;
};

type CameraDevice = {
  deviceId: string;
  label: string;
};

const MAX_CAPTURE_SIDE = 2560;
const CAMERA_ACCEPT = 'image/jpeg,image/png,image/webp';
const MOBILE_UA_PATTERN = /Android|iPhone|iPad|iPod|Mobile|Tablet/i;
const FOCUSABLE_SELECTOR = 'button:not([disabled]), [href], input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])';

export function isMobileCaptureDevice(win: Window = window, nav: Navigator = navigator) {
  const mediaQuery = typeof win.matchMedia === 'function' ? win.matchMedia('(pointer: coarse)') : null;
  if (mediaQuery?.matches) return true;
  return MOBILE_UA_PATTERN.test(nav.userAgent || '');
}

function stopMediaStream(stream: MediaStream | null) {
  stream?.getTracks().forEach((track) => track.stop());
}

function cameraErrorMessage(error: unknown) {
  const name = error instanceof DOMException ? error.name : error instanceof Error ? error.name : '';
  if (typeof window !== 'undefined' && !window.isSecureContext) {
    return 'Live camera needs HTTPS or localhost. Use Upload file here, or open the alpha through the secure phone URL.';
  }
  if (name === 'NotAllowedError' || name === 'PermissionDeniedError') return 'Camera permission was blocked. Allow camera access in the browser, or use Upload file.';
  if (name === 'NotFoundError' || name === 'DevicesNotFoundError') return 'No camera was found on this device. Use Upload file instead.';
  if (name === 'NotReadableError' || name === 'TrackStartError') return 'The camera is busy in another app. Close that app and try again, or use Upload file.';
  if (name === 'OverconstrainedError' || name === 'ConstraintNotSatisfiedError') return 'That camera could not start with the requested settings. Try another camera or use Upload file.';
  if (name === 'SecurityError') return 'This browser blocked camera access for this page. Use HTTPS/local testing or Upload file.';
  return 'Live camera is not available in this browser. Use Upload file instead.';
}

function cameraConstraints(deviceId: string | null): MediaStreamConstraints {
  return {
    audio: false,
    video: deviceId
      ? { deviceId: { exact: deviceId }, width: { ideal: 1920 }, height: { ideal: 1440 } }
      : { facingMode: { ideal: 'environment' }, width: { ideal: 1920 }, height: { ideal: 1440 } },
  };
}

function listVideoDevices(devices: MediaDeviceInfo[]) {
  return devices
    .filter((device) => device.kind === 'videoinput' && device.deviceId)
    .map((device, index) => ({
      deviceId: device.deviceId,
      label: device.label || `Camera ${index + 1}`,
    }));
}

export function MobileCameraButton({ onCapture, label = 'Take photo', className }: MobileCameraButtonProps) {
  const titleId = useId();
  const descriptionId = useId();
  const videoRef = useRef<HTMLVideoElement | null>(null);
  const dialogRef = useRef<HTMLDivElement | null>(null);
  const fileInputRef = useRef<HTMLInputElement | null>(null);
  const openerRef = useRef<HTMLElement | null>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const openRef = useRef(false);
  const requestSeq = useRef(0);
  const restoreFocusRef = useRef(false);

  const [shouldRender, setShouldRender] = useState(false);
  const [open, setOpen] = useState(false);
  const [status, setStatus] = useState('');
  const [error, setError] = useState('');
  const [ready, setReady] = useState(false);
  const [busy, setBusy] = useState(false);
  const [devices, setDevices] = useState<CameraDevice[]>([]);
  const [selectedDeviceId, setSelectedDeviceId] = useState('');

  const stopCurrentStream = useCallback(() => {
    requestSeq.current += 1;
    const stream = streamRef.current;
    streamRef.current = null;
    stopMediaStream(stream);
    if (videoRef.current) videoRef.current.srcObject = null;
    setReady(false);
    setBusy(false);
  }, []);

  const closeDialog = useCallback((restoreFocus = true) => {
    restoreFocusRef.current = restoreFocus;
    openRef.current = false;
    setOpen(false);
    setError('');
    setStatus('');
    stopCurrentStream();
  }, [stopCurrentStream]);

  const startCamera = useCallback(async (deviceId: string | null = null) => {
    const mediaDevices = navigator.mediaDevices;
    if (!mediaDevices?.getUserMedia) {
      setError(cameraErrorMessage(new Error('MediaDevices unavailable')));
      setStatus('');
      setBusy(false);
      return;
    }

    stopCurrentStream();
    const seq = requestSeq.current;
    setBusy(true);
    setReady(false);
    setError('');
    setStatus(deviceId ? 'Switching camera…' : 'Starting rear camera…');

    try {
      const stream = await mediaDevices.getUserMedia(cameraConstraints(deviceId));
      if (!openRef.current || seq !== requestSeq.current) {
        stopMediaStream(stream);
        return;
      }
      streamRef.current = stream;
      const video = videoRef.current;
      if (video) {
        video.srcObject = stream;
        await video.play().catch(() => undefined);
        if (!openRef.current || seq !== requestSeq.current) {
          if (streamRef.current === stream) {
            stopMediaStream(stream);
            streamRef.current = null;
          }
          return;
        }
        if (video.readyState >= 2 && video.videoWidth > 0 && video.videoHeight > 0) setReady(true);
      }
      const settingsDeviceId = stream.getVideoTracks()[0]?.getSettings().deviceId || deviceId || '';
      setSelectedDeviceId(settingsDeviceId);
      setStatus('Camera ready. Keep the character flat and well lit.');

      if (mediaDevices.enumerateDevices) {
        const availableDevices = listVideoDevices(await mediaDevices.enumerateDevices());
        if (openRef.current && seq === requestSeq.current) setDevices(availableDevices);
      }
    } catch (err) {
      if (openRef.current && seq === requestSeq.current) {
        setError(cameraErrorMessage(err));
        setStatus('');
      }
    } finally {
      if (openRef.current && seq === requestSeq.current) setBusy(false);
    }
  }, [stopCurrentStream]);

  const openDialog = useCallback(() => {
    openerRef.current = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    openRef.current = true;
    setOpen(true);
    setDevices([]);
    setSelectedDeviceId('');
    void startCamera(null);
  }, [startCamera]);

  useEffect(() => {
    function updateRenderState() {
      const nextShouldRender = isMobileCaptureDevice();
      setShouldRender(nextShouldRender);
      if (!nextShouldRender && openRef.current) closeDialog(false);
    }
    updateRenderState();
    const pointerQuery = window.matchMedia?.('(pointer: coarse)');
    pointerQuery?.addEventListener?.('change', updateRenderState);
    return () => pointerQuery?.removeEventListener?.('change', updateRenderState);
  }, [closeDialog]);

  useEffect(() => {
    if (!open) return;
    const firstButton = dialogRef.current?.querySelector<HTMLElement>(FOCUSABLE_SELECTOR);
    firstButton?.focus();
  }, [open]);

  useEffect(() => {
    openRef.current = open;
    if (!open) {
      if (restoreFocusRef.current) setTimeout(() => openerRef.current?.focus(), 0);
      return;
    }

    function onKeyDown(event: KeyboardEvent) {
      if (event.key === 'Escape') {
        event.preventDefault();
        closeDialog();
        return;
      }
      if (event.key !== 'Tab') return;
      const focusable = Array.from(dialogRef.current?.querySelectorAll<HTMLElement>(FOCUSABLE_SELECTOR) ?? []).filter((element) => element.offsetParent !== null || element === document.activeElement);
      if (focusable.length === 0) return;
      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    }

    function onVisibilityChange() {
      if (document.visibilityState === 'hidden') closeDialog(false);
    }

    function onPageHide() {
      closeDialog(false);
    }

    document.addEventListener('keydown', onKeyDown);
    document.addEventListener('visibilitychange', onVisibilityChange);
    window.addEventListener('pagehide', onPageHide);
    return () => {
      document.removeEventListener('keydown', onKeyDown);
      document.removeEventListener('visibilitychange', onVisibilityChange);
      window.removeEventListener('pagehide', onPageHide);
    };
  }, [closeDialog, open]);

  useEffect(() => () => {
    openRef.current = false;
    requestSeq.current += 1;
    stopMediaStream(streamRef.current);
    streamRef.current = null;
    if (videoRef.current) videoRef.current.srcObject = null;
  }, []);

  async function capturePhoto() {
    const video = videoRef.current;
    if (!video || !ready || video.readyState < 2 || video.videoWidth <= 0 || video.videoHeight <= 0) return;
    const seq = requestSeq.current;
    setBusy(true);
    setError('');
    try {
      const scale = Math.min(1, MAX_CAPTURE_SIDE / Math.max(video.videoWidth, video.videoHeight));
      const canvas = document.createElement('canvas');
      canvas.width = Math.max(1, Math.round(video.videoWidth * scale));
      canvas.height = Math.max(1, Math.round(video.videoHeight * scale));
      const context = canvas.getContext('2d');
      if (!context) throw new Error('Canvas unavailable');
      context.drawImage(video, 0, 0, canvas.width, canvas.height);
      const blob = await new Promise<Blob | null>((resolve) => canvas.toBlob(resolve, 'image/jpeg', 0.92));
      if (!openRef.current || seq !== requestSeq.current) return;
      if (!blob) throw new Error('JPEG export failed');
      onCapture(new File([blob], `camera-${Date.now()}.jpg`, { type: 'image/jpeg', lastModified: Date.now() }));
      closeDialog();
    } catch {
      if (openRef.current && seq === requestSeq.current) setError('Could not capture a photo from this camera. Try again or use Upload file.');
    } finally {
      if (openRef.current && seq === requestSeq.current) setBusy(false);
    }
  }

  function handleDeviceChange(event: ChangeEvent<HTMLSelectElement>) {
    const nextDeviceId = event.target.value;
    setSelectedDeviceId(nextDeviceId);
    void startCamera(nextDeviceId);
  }

  function handleFallbackFile(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    if (file) {
      onCapture(file);
      closeDialog();
    }
    event.target.value = '';
  }

  if (!shouldRender) return null;

  return (
    <>
      <button type="button" onClick={openDialog} className={className}>
        {label}
      </button>
      <input ref={fileInputRef} type="file" accept={CAMERA_ACCEPT} capture="environment" className="hidden" onChange={handleFallbackFile} />
      {open ? (
        <div className="fixed inset-0 z-[80] grid place-items-center bg-black/70 p-3" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget) closeDialog(); }}>
          <div ref={dialogRef} role="dialog" aria-modal="true" aria-labelledby={titleId} aria-describedby={descriptionId} className="grid max-h-[92dvh] w-full max-w-[520px] gap-4 overflow-auto rounded-[28px] border border-white/15 bg-surface p-4 text-left shadow-2xl">
            <div className="flex items-start justify-between gap-3">
              <div>
                <h2 id={titleId} className="text-lg font-bold text-text-primary">Phone camera</h2>
                <p id={descriptionId} className="mt-1 text-sm text-text-secondary">Use the back camera when available. The browser may list more than one camera.</p>
              </div>
              <button type="button" onClick={() => closeDialog()} className="secondary-button shrink-0 whitespace-nowrap" aria-label="Close camera">Close</button>
            </div>

            <div className="relative overflow-hidden rounded-2xl border border-border bg-black">
              <video ref={videoRef} className="aspect-[4/3] w-full object-contain" autoPlay muted playsInline onLoadedData={() => setReady(Boolean(videoRef.current && videoRef.current.readyState >= 2 && videoRef.current.videoWidth && videoRef.current.videoHeight))} onCanPlay={() => setReady(Boolean(videoRef.current && videoRef.current.readyState >= 2 && videoRef.current.videoWidth && videoRef.current.videoHeight))} aria-label="Live camera preview" />
              {!ready && !error ? <div className="absolute inset-0 grid place-items-center bg-black/45 px-4 text-center text-sm font-semibold text-white">{busy ? 'Opening camera…' : 'Waiting for camera preview…'}</div> : null}
            </div>

            {devices.length > 1 ? (
              <label className="grid gap-1.5 text-sm font-semibold text-text-primary">
                Camera
                <select value={selectedDeviceId} onChange={handleDeviceChange} disabled={busy} className="field">
                  {devices.map((device) => <option key={device.deviceId} value={device.deviceId}>{device.label}</option>)}
                </select>
              </label>
            ) : null}

            {error ? <p role="alert" className="rounded-xl border border-amber/30 bg-amber/10 px-3 py-2 text-sm text-text-primary">{error}</p> : null}
            {status && !error ? <p role="status" className="text-sm text-text-secondary">{status}</p> : null}

            <div className="grid grid-cols-2 gap-2 sm:flex sm:flex-wrap sm:justify-end">
              <button type="button" onClick={() => { closeDialog(false); fileInputRef.current?.click(); }} className="secondary-button">Use phone picker</button>
              <button type="button" onClick={capturePhoto} disabled={!ready || busy} className="primary-button">Capture photo</button>
            </div>
          </div>
        </div>
      ) : null}
    </>
  );
}
