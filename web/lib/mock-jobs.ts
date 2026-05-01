import { JOB_RETENTION_HOURS, type JobResponse, retentionExpiry } from './contracts';

export const demoSuccessJob: JobResponse = {
  jobId: 'demo_job_template_v1',
  status: 'succeeded',
  stage: 'complete',
  progressLabel: 'Demo font generated from the bundled synthetic template',
  warnings: [
    {
      code: 'GLYPH_LOW_INK_COVERAGE',
      glyph: ',',
      message: 'Comma has low ink coverage. Tiny punctuation can still be valid.',
      severity: 'warning',
      details: { coverageRatio: 0.012 }
    }
  ],
  artifacts: [
    {
      kind: 'otf',
      label: 'OpenType Font',
      objectKey: '/sample-output/template-v1-synthetic/TemplateV1Synthetic.otf',
      url: '/sample-output/template-v1-synthetic/TemplateV1Synthetic.otf',
      contentType: 'font/otf',
      sizeBytes: 1
    },
    {
      kind: 'ttf',
      label: 'TrueType Font',
      objectKey: '/sample-output/template-v1-synthetic/TemplateV1Synthetic.ttf',
      url: '/sample-output/template-v1-synthetic/TemplateV1Synthetic.ttf',
      contentType: 'font/ttf',
      sizeBytes: 1
    }
  ],
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
