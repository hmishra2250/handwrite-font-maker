import { describe, expect, it } from 'vitest';
import { DEFAULT_ADAPTIVE_LOCAL_OFFSET, DEFAULT_ADAPTIVE_LOCAL_RADIUS, buildInkMask } from '@/lib/ink-mask';

function rgbaPixels(values: [number, number, number, number][]) {
  return new Uint8ClampedArray(values.flat());
}

function grayImage(width: number, height: number, valueAt: (x: number, y: number) => number) {
  const data = new Uint8ClampedArray(width * height * 4);
  for (let y = 0; y < height; y++) {
    for (let x = 0; x < width; x++) {
      const offset = (y * width + x) * 4;
      const value = valueAt(x, y);
      data[offset] = value;
      data[offset + 1] = value;
      data[offset + 2] = value;
      data[offset + 3] = 255;
    }
  }
  return data;
}

function isForeground(mask: Uint8ClampedArray, width: number, x: number, y: number) {
  return mask[(y * width + x) * 4] === 0;
}

describe('buildInkMask', () => {
  it('preserves legacy opaque global-threshold output and forced opaque alpha', () => {
    const result = buildInkMask(rgbaPixels([
      [0, 0, 0, 255],
      [80, 80, 80, 255],
      [200, 200, 200, 255],
      [255, 255, 255, 255],
    ]), 4, 1, { method: 'global', threshold: 170 });
    expect(Array.from(result.data)).toEqual([
      0, 0, 0, 255,
      0, 0, 0, 255,
      255, 255, 255, 255,
      255, 255, 255, 255,
    ]);
    expect(result.foreground).toBe(2);
  });

  it('composites transparent pixels over white instead of turning transparent black into foreground', () => {
    const result = buildInkMask(rgbaPixels([
      [0, 0, 0, 0],
      [0, 0, 0, 128],
      [0, 0, 0, 255],
    ]), 3, 1, { method: 'global', threshold: 170 });
    expect(isForeground(result.data, 3, 0, 0)).toBe(false);
    expect(isForeground(result.data, 3, 1, 0)).toBe(true);
    expect(isForeground(result.data, 3, 2, 0)).toBe(true);
  });

  it('applies invert semantics after white alpha compositing', () => {
    const result = buildInkMask(rgbaPixels([
      [250, 250, 250, 255],
      [20, 20, 20, 255],
      [255, 255, 255, 0],
    ]), 3, 1, { method: 'global', threshold: 170, invert: true });
    expect(isForeground(result.data, 3, 0, 0)).toBe(true);
    expect(isForeground(result.data, 3, 1, 0)).toBe(false);
    expect(isForeground(result.data, 3, 2, 0)).toBe(true);
  });

  it('applies adaptive invert semantics around the local mean', () => {
    const width = 3;
    const height = 3;
    const data = grayImage(width, height, (x, y) => (x === 1 && y === 1 ? 250 : 120));
    const result = buildInkMask(data, width, height, { method: 'adaptive', invert: true, localRadius: 1, localOffset: 30 });
    expect(isForeground(result.data, width, 1, 1)).toBe(true);
    expect(isForeground(result.data, width, 0, 0)).toBe(false);
  });

  it('uses local mean thresholding to avoid classifying page shadow as ink', () => {
    const width = 5;
    const height = 3;
    const shadowedStroke = grayImage(width, height, (x, y) => {
      const background = 220 - x * 18;
      return y === 1 && x === 2 ? 45 : background;
    });
    const global = buildInkMask(shadowedStroke, width, height, { method: 'global', threshold: 170 });
    const adaptive = buildInkMask(shadowedStroke, width, height, { method: 'adaptive', localRadius: 1, localOffset: 35 });

    expect(isForeground(global.data, width, 4, 0)).toBe(true);
    expect(isForeground(adaptive.data, width, 4, 0)).toBe(false);
    expect(isForeground(adaptive.data, width, 2, 1)).toBe(true);
  });

  it('keeps thin strokes, counters, and isolated dots without component deletion', () => {
    const width = 7;
    const height = 7;
    const data = grayImage(width, height, (x, y) => {
      const ring = x >= 1 && x <= 3 && y >= 1 && y <= 3 && (x === 1 || x === 3 || y === 1 || y === 3);
      const counter = x === 2 && y === 2;
      const dot = x === 5 && y === 5;
      return (ring && !counter) || dot ? 20 : 245;
    });
    const result = buildInkMask(data, width, height, { method: 'global', threshold: 170 });

    expect(isForeground(result.data, width, 1, 1)).toBe(true);
    expect(isForeground(result.data, width, 2, 2)).toBe(false);
    expect(isForeground(result.data, width, 5, 5)).toBe(true);
    expect(result.foreground).toBe(9);
  });

  it('freezes the default adaptive local threshold constants used by held-out panels', () => {
    expect(DEFAULT_ADAPTIVE_LOCAL_RADIUS).toBe(12);
    expect(DEFAULT_ADAPTIVE_LOCAL_OFFSET).toBe(18);
  });

  it('rejects invalid, non-integer, and zero dimensions instead of silently clamping', () => {
    const source = new Uint8ClampedArray(16);
    expect(() => buildInkMask(source, 0, 1)).toThrow(/width must be a positive integer/);
    expect(() => buildInkMask(source, 1.5, 1)).toThrow(/width must be a positive integer/);
    expect(() => buildInkMask(source, 1, Number.NaN)).toThrow(/height must be a positive integer/);
  });

  it('rejects source buffers smaller than width by height', () => {
    expect(() => buildInkMask(new Uint8ClampedArray(3), 2, 2)).toThrow(/smaller/);
  });

  it('rejects non-finite threshold parameters', () => {
    expect(() => buildInkMask(new Uint8ClampedArray(4), 1, 1, { threshold: Number.NaN })).toThrow(/threshold must be finite/);
    expect(() => buildInkMask(new Uint8ClampedArray(4), 1, 1, { method: 'adaptive', localRadius: Number.POSITIVE_INFINITY })).toThrow(/localRadius must be finite/);
    expect(() => buildInkMask(new Uint8ClampedArray(4), 1, 1, { method: 'adaptive', localOffset: Number.NEGATIVE_INFINITY })).toThrow(/localOffset must be finite/);
  });
});
