import { describe, expect, it } from 'vitest';
import { HARD_ERROR_CODES, isSafeFontName, isSupportedImage, validateCaptureConfig } from '@/lib/contracts';

describe('web contract', () => {
  it('keeps hard error taxonomy for capture and font failures', () => {
    expect(HARD_ERROR_CODES).toContain('MARKER_GEOMETRY_INVALID');
    expect(HARD_ERROR_CODES).toContain('RECTIFIED_PAGE_OUT_OF_BOUNDS');
    expect(HARD_ERROR_CODES).toContain('GLYPH_REQUIRED_SET_MISSING');
    expect(HARD_ERROR_CODES).toContain('FONT_VALIDATION_FAILED');
    expect(HARD_ERROR_CODES).toContain('CAPTURE_CONFIG_INVALID');
  });

  it('validates image and font metadata locally', () => {
    expect(isSupportedImage('image/jpeg')).toBe(true);
    expect(isSupportedImage('image/png')).toBe(true);
    expect(isSupportedImage('application/pdf')).toBe(false);
    expect(isSafeFontName('MyFont-Regular')).toBe(true);
    expect(isSafeFontName('bad font')).toBe(false);
  });

  it('accepts frozen markerless template capture config only with confirmed corners', () => {
    const valid = {
      mode: 'template',
      templateId: 'default-v1',
      paperSize: 'A4',
      alignment: 'page',
      corners: [[0.1, 0.1], [0.9, 0.1], [0.9, 0.9], [0.1, 0.9]],
    };
    expect(validateCaptureConfig(valid)).toBeNull();
    expect(validateCaptureConfig({ ...valid, paperSize: 'Letter' })).toContain('A4');
    expect(validateCaptureConfig({ ...valid, corners: undefined })).toContain('corners');
  });

  it('accepts guided mask-v1 glyph configs and rejects duplicate or unsupported labels', () => {
    const inputPhoto = { objectKey: 'jobs/test/input/glyph.png', contentType: 'image/png', sizeBytes: 500 };
    expect(validateCaptureConfig({ mode: 'guided', format: 'mask-v1', glyphs: [{ char: 'A', inputPhoto, baseline: 0.8 }] })).toBeNull();
    expect(validateCaptureConfig({ mode: 'guided', format: 'mask-v1', glyphs: [{ char: ' ', inputPhoto, baseline: 0.8 }] })).toContain('printable');
    expect(validateCaptureConfig({ mode: 'guided', format: 'mask-v1', glyphs: [{ char: 'A', inputPhoto, baseline: 0.8 }, { char: 'A', inputPhoto, baseline: 0.7 }] })).toContain('unique');
    expect(validateCaptureConfig({ mode: 'guided', format: 'mask-v1', glyphs: [{ char: 'A', inputPhoto, baseline: 1 }] })).toContain('baseline');
  });
});
