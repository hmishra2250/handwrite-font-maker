export type InkMaskMethod = 'global' | 'adaptive';

export interface InkMaskOptions {
  method?: InkMaskMethod;
  threshold?: number;
  invert?: boolean;
  localRadius?: number;
  localOffset?: number;
}

export interface InkMaskResult {
  data: Uint8ClampedArray;
  foreground: number;
}

const DEFAULT_THRESHOLD = 170;
export const DEFAULT_ADAPTIVE_LOCAL_RADIUS = 12;
export const DEFAULT_ADAPTIVE_LOCAL_OFFSET = 18;

function boundedIntegerParam(value: number | undefined, fallback: number, min: number, max: number, name: string) {
  if (value === undefined) return fallback;
  if (!Number.isFinite(value)) throw new Error(`${name} must be finite.`);
  return Math.min(max, Math.max(min, Math.round(value as number)));
}

function validateDimension(value: number, name: string) {
  if (!Number.isFinite(value) || !Number.isInteger(value) || value <= 0) throw new Error(`${name} must be a positive integer.`);
  return value;
}

function compositedLuma(source: ArrayLike<number>, pixelOffset: number) {
  const alpha = Math.min(255, Math.max(0, source[pixelOffset + 3] ?? 255)) / 255;
  const r = (source[pixelOffset] ?? 0) * alpha + 255 * (1 - alpha);
  const g = (source[pixelOffset + 1] ?? 0) * alpha + 255 * (1 - alpha);
  const b = (source[pixelOffset + 2] ?? 0) * alpha + 255 * (1 - alpha);
  return 0.299 * r + 0.587 * g + 0.114 * b;
}

export function buildInkMask(source: ArrayLike<number>, width: number, height: number, options: InkMaskOptions = {}): InkMaskResult {
  const safeWidth = validateDimension(width, 'width');
  const safeHeight = validateDimension(height, 'height');
  if (safeWidth * safeHeight * 4 > source.length) throw new Error('Ink mask source data is smaller than width × height.');

  const method: InkMaskMethod = options.method === 'adaptive' ? 'adaptive' : 'global';
  const threshold = boundedIntegerParam(options.threshold, DEFAULT_THRESHOLD, 1, 254, 'threshold');
  const invert = Boolean(options.invert);
  const lumas = new Float64Array(safeWidth * safeHeight);
  for (let pixel = 0; pixel < lumas.length; pixel++) lumas[pixel] = compositedLuma(source, pixel * 4);

  const mask = new Uint8ClampedArray(safeWidth * safeHeight * 4);
  let foreground = 0;

  if (method === 'global') {
    for (let pixel = 0; pixel < lumas.length; pixel++) {
      const isForeground = invert ? lumas[pixel] > threshold : lumas[pixel] < threshold;
      const value = isForeground ? 0 : 255;
      const offset = pixel * 4;
      mask[offset] = value;
      mask[offset + 1] = value;
      mask[offset + 2] = value;
      mask[offset + 3] = 255;
      if (isForeground) foreground++;
    }
    return { data: mask, foreground };
  }

  const radius = boundedIntegerParam(options.localRadius, DEFAULT_ADAPTIVE_LOCAL_RADIUS, 1, Math.max(1, Math.min(safeWidth, safeHeight)), 'localRadius');
  const localOffset = boundedIntegerParam(options.localOffset, DEFAULT_ADAPTIVE_LOCAL_OFFSET, 0, 254, 'localOffset');
  const integralWidth = safeWidth + 1;
  const integral = new Float64Array((safeWidth + 1) * (safeHeight + 1));
  for (let y = 0; y < safeHeight; y++) {
    let rowSum = 0;
    for (let x = 0; x < safeWidth; x++) {
      rowSum += lumas[y * safeWidth + x] ?? 0;
      const integralIndex = (y + 1) * integralWidth + (x + 1);
      integral[integralIndex] = (integral[integralIndex - integralWidth] ?? 0) + rowSum;
    }
  }

  for (let y = 0; y < safeHeight; y++) {
    const top = Math.max(0, y - radius);
    const bottom = Math.min(safeHeight - 1, y + radius);
    for (let x = 0; x < safeWidth; x++) {
      const left = Math.max(0, x - radius);
      const right = Math.min(safeWidth - 1, x + radius);
      const area = (right - left + 1) * (bottom - top + 1);
      const sum = integral[(bottom + 1) * integralWidth + (right + 1)]
        - integral[top * integralWidth + (right + 1)]
        - integral[(bottom + 1) * integralWidth + left]
        + integral[top * integralWidth + left];
      const mean = sum / area;
      const luma = lumas[y * safeWidth + x] ?? 255;
      const isForeground = invert ? luma > mean + localOffset : luma < mean - localOffset;
      const value = isForeground ? 0 : 255;
      const offset = (y * safeWidth + x) * 4;
      mask[offset] = value;
      mask[offset + 1] = value;
      mask[offset + 2] = value;
      mask[offset + 3] = 255;
      if (isForeground) foreground++;
    }
  }
  return { data: mask, foreground };
}
