import { describe, expect, it } from 'vitest';
import { HARD_ERROR_CODES, isSafeFontName, isSupportedImage } from '@/lib/contracts';

describe('web contract', () => {
  it('keeps full hard error taxonomy from the PRD', () => {
    expect(HARD_ERROR_CODES).toContain('MARKER_GEOMETRY_INVALID');
    expect(HARD_ERROR_CODES).toContain('QR_TEMPLATE_MISMATCH');
    expect(HARD_ERROR_CODES).toContain('RECTIFIED_PAGE_OUT_OF_BOUNDS');
    expect(HARD_ERROR_CODES).toContain('GLYPH_REQUIRED_SET_MISSING');
    expect(HARD_ERROR_CODES).toContain('FONT_VALIDATION_FAILED');
  });

  it('validates image and font metadata locally', () => {
    expect(isSupportedImage('image/jpeg')).toBe(true);
    expect(isSupportedImage('application/pdf')).toBe(false);
    expect(isSafeFontName('MyFont-Regular')).toBe(true);
    expect(isSafeFontName('bad font')).toBe(false);
  });
});
