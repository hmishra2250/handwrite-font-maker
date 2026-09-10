import { JOB_RETENTION_HOURS, type JobResponse, retentionExpiry } from './contracts';

export const demoBackendUnavailable: JobResponse = {
  jobId: 'demo_backend_unavailable',
  status: 'failed',
  stage: 'queued',
  progressLabel: 'No Python worker is configured for local font builds.',
  warnings: [],
  artifacts: [],
  error: {
    code: 'INTERNAL_ERROR',
    message: 'Configure WORKER_API_BASE_URL to run real upload, capture, and font-generation jobs. Demo mode does not publish fake font files.',
    retryable: true
  },
  retentionExpiresAt: retentionExpiry(JOB_RETENTION_HOURS)
};

export const demoMarkerFailure: JobResponse = {
  jobId: 'demo_marker_failure',
  status: 'failed',
  stage: 'marker_detection',
  progressLabel: 'Could not verify page markers',
  warnings: [],
  artifacts: [],
  error: {
    code: 'MARKER_NOT_FOUND',
    message: 'We could not find all four page markers. Retake the photo with the entire page visible.',
    retryable: true,
    details: { missingCorners: ['bottom_left'] }
  },
  retentionExpiresAt: retentionExpiry(JOB_RETENTION_HOURS)
};
